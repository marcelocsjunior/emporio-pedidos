from __future__ import annotations

import csv
import hashlib
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from customer_portal.models import CustomerDeliveryLocation

from .models import AuditEvent, Company, CompanyImportBatch, CompanyImportItem
from .services import record_audit

MAX_FILE_SIZE = 2 * 1024 * 1024
MAX_RECORDS = 2_000
MAX_COLUMNS = 40
MAX_FIELD_LENGTH = 1_000
MAX_XML_DEPTH = 8
SUPPORTED_FIELDS = (
    "name",
    "entity_type",
    "document",
    "responsible_name",
    "phone",
    "email",
    "address",
    "city",
    "state",
    "postal_code",
    "customer_type",
    "payment_terms",
    "source_system",
    "external_id",
    "notes",
    "delivery_location_label",
    "delivery_location_address",
    "delivery_location_city",
)
DELIVERY_LOCATION_FIELDS = {
    "delivery_location_label",
    "delivery_location_address",
    "delivery_location_city",
}


class ImportFileError(ValueError):
    pass


@dataclass
class ParsedFile:
    headers: list[str]
    rows: list[dict[str, str]]
    file_format: str
    separator: str = ""
    encoding: str = "utf-8"


@dataclass
class PreviewRow:
    number: int
    status: str
    reason: str
    values: dict[str, str]
    warning: str = ""


def safe_filename(name: str) -> str:
    name = Path(name).name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "_", name).strip(". ")
    return (cleaned or "arquivo")[:255]


def file_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate_size(content: bytes) -> None:
    if not content:
        raise ImportFileError("O arquivo está vazio.")
    if len(content) > MAX_FILE_SIZE:
        raise ImportFileError("O arquivo excede o limite de 2 MB.")


def parse_file(content: bytes, filename: str) -> ParsedFile:
    _validate_size(content)
    suffix = Path(filename).suffix.lower()
    if suffix == ".csv":
        return parse_csv(content)
    if suffix == ".xml":
        return parse_xml(content)
    raise ImportFileError("Envie um arquivo CSV ou XML.")


def parse_csv(content: bytes) -> ParsedFile:
    _validate_size(content)
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportFileError("O CSV deve usar codificação UTF-8.") from exc
    if "\x00" in text:
        raise ImportFileError("O CSV contém estrutura inválida.")
    try:
        sample = text[:8192]
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        if not csv.Sniffer().has_header(sample):
            raise ImportFileError("O CSV deve conter uma linha de cabeçalho.")
        reader = csv.reader(io.StringIO(text), dialect=dialect, strict=True)
        raw_headers = next(reader)
        headers = [header.strip() for header in raw_headers]
        if (
            not headers
            or any(not header for header in headers)
            or len(set(headers)) != len(headers)
        ):
            raise ImportFileError("O cabeçalho do CSV é inválido ou duplicado.")
        if len(headers) > MAX_COLUMNS:
            raise ImportFileError("O CSV excede o limite de 40 colunas.")
        rows = []
        for number, values in enumerate(reader, start=2):
            if len(values) != len(headers):
                raise ImportFileError(f"A linha {number} possui quantidade inválida de colunas.")
            if any(len(value) > MAX_FIELD_LENGTH for value in values):
                raise ImportFileError(f"A linha {number} contém campo acima do limite.")
            if not any(value.strip() for value in values):
                continue
            rows.append(dict(zip(headers, (value.strip() for value in values), strict=True)))
            if len(rows) > MAX_RECORDS:
                raise ImportFileError("O arquivo excede o limite de 2.000 registros.")
    except (csv.Error, StopIteration) as exc:
        raise ImportFileError("O CSV está malformado.") from exc
    return ParsedFile(
        headers,
        rows,
        "csv",
        dialect.delimiter,
        "utf-8-sig" if content.startswith(b"\xef\xbb\xbf") else "utf-8",
    )


def _depth(element: ET.Element, current: int = 1) -> int:
    return max([current, *(_depth(child, current + 1) for child in element)])


def parse_xml(content: bytes) -> ParsedFile:
    _validate_size(content)
    upper = content.upper()
    if b"<!DOCTYPE" in upper or b"<!ENTITY" in upper:
        raise ImportFileError("XML com DTD ou entidades não é permitido.")
    try:
        root = ET.fromstring(content)
    except (ET.ParseError, ValueError) as exc:
        raise ImportFileError("O XML está malformado.") from exc
    if _depth(root) > MAX_XML_DEPTH:
        raise ImportFileError("O XML excede a profundidade máxima de 8 níveis.")
    records = list(root)
    if not records or len(records) > MAX_RECORDS:
        raise ImportFileError("O XML deve conter entre 1 e 2.000 registros simples.")
    headers: list[str] = []
    rows: list[dict[str, str]] = []
    for record in records:
        row: dict[str, str] = {}
        for child in record:
            if list(child) or child.attrib:
                raise ImportFileError("O XML deve usar elementos simples, sem atributos.")
            key = child.tag.split("}")[-1]
            value = (child.text or "").strip()
            if len(value) > MAX_FIELD_LENGTH:
                raise ImportFileError("O XML contém campo acima do limite.")
            if key in row:
                raise ImportFileError("O XML contém elemento duplicado no mesmo registro.")
            row[key] = value
            if key not in headers:
                headers.append(key)
        rows.append(row)
    if not headers or len(headers) > MAX_COLUMNS:
        raise ImportFileError("O XML não possui estrutura válida ou excede 40 elementos.")
    return ParsedFile(headers, rows, "xml")


def validate_mapping(mapping: dict[str, str], headers: list[str]) -> dict[str, str]:
    cleaned = {source: target for source, target in mapping.items() if target}
    if any(
        source not in headers or target not in SUPPORTED_FIELDS
        for source, target in cleaned.items()
    ):
        raise ImportFileError("O mapeamento contém campo não reconhecido.")
    if len(set(cleaned.values())) != len(cleaned):
        raise ImportFileError("Cada campo do sistema pode ser associado somente uma vez.")
    if "name" not in cleaned.values():
        raise ImportFileError("Associe uma coluna ou elemento ao campo Nome/razão social.")
    return cleaned


def _mapped(row: dict[str, str], mapping: dict[str, str]) -> dict[str, str]:
    return {target: row.get(source, "").strip() for source, target in mapping.items()}


def _split_values(values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    company_values = {
        key: value for key, value in values.items() if key not in DELIVERY_LOCATION_FIELDS
    }
    location_values = {
        "label": values.get("delivery_location_label", ""),
        "address": values.get("delivery_location_address", ""),
        "city": values.get("delivery_location_city", ""),
    }
    return company_values, location_values


def preview_rows(parsed: ParsedFile, mapping: dict[str, str]) -> list[PreviewRow]:
    mapping = validate_mapping(mapping, parsed.headers)
    seen_documents: set[str] = set()
    seen_external: set[tuple[str, str]] = set()
    previews: list[PreviewRow] = []
    for number, raw in enumerate(parsed.rows, start=1):
        values = _mapped(raw, mapping)
        if not any(values.values()):
            previews.append(PreviewRow(number, "ignored", "Registro vazio.", values))
            continue
        company_values, location_values = _split_values(values)
        company = Company(**company_values)
        reason = ""
        status = "valid"
        try:
            company.full_clean(validate_unique=False, validate_constraints=False)
            validate_email(company.email) if company.email else None
            has_location_data = any(location_values.values())
            has_required_location_data = bool(
                location_values["label"] and location_values["address"]
            )
            if has_location_data and not has_required_location_data:
                raise ValidationError(
                    "Para importar um local de entrega, preencha identificação e endereço. "
                    "A cidade é opcional, mas não pode ser informada isoladamente."
                )
            if has_required_location_data:
                location = CustomerDeliveryLocation(**location_values)
                location.clean_fields(exclude=("company", "active"))
        except ValidationError as exc:
            messages = exc.messages
            reason = "; ".join(dict.fromkeys(messages))[:500]
            status = "incomplete" if not values.get("name") else "invalid"
        document = company.document
        external = (company.source_system, company.external_id)
        if (
            status == "valid"
            and document
            and (document in seen_documents or Company.objects.filter(document=document).exists())
        ):
            status, reason = "duplicate", "Documento já cadastrado ou repetido no arquivo."
        elif (
            status == "valid"
            and all(external)
            and (
                external in seen_external
                or Company.objects.filter(
                    source_system=external[0], external_id=external[1]
                ).exists()
            )
        ):
            status, reason = (
                "duplicate",
                "Origem e ID externo já cadastrados ou repetidos no arquivo.",
            )
        warning = ""
        if status == "valid" and Company.objects.filter(name__iexact=company.name).exists():
            warning = "Nome igual a cadastro existente; confira antes de importar."
        if document:
            seen_documents.add(document)
        if all(external):
            seen_external.add(external)
        previews.append(PreviewRow(number, status, reason, values, warning))
    return previews


def apply_preview(
    batch: CompanyImportBatch, parsed: ParsedFile, mapping: dict[str, str], actor
) -> list[PreviewRow]:
    previews = preview_rows(parsed, mapping)
    batch.mapping = mapping
    batch.total_count = len(previews)
    batch.valid_count = sum(row.status == "valid" for row in previews)
    batch.invalid_count = sum(row.status in {"invalid", "incomplete"} for row in previews)
    batch.duplicate_count = sum(row.status == "duplicate" for row in previews)
    batch.ignored_count = sum(row.status == "ignored" for row in previews)
    batch.status = CompanyImportBatch.Status.PREVIEWED
    batch.save()
    record_audit(
        actor=actor,
        action="company_import.previewed",
        entity=batch,
        payload={
            "total": batch.total_count,
            "valid": batch.valid_count,
            "invalid": batch.invalid_count,
            "duplicates": batch.duplicate_count,
        },
    )
    return previews


def execute_import(batch: CompanyImportBatch, parsed: ParsedFile, actor) -> int:
    previews = preview_rows(parsed, batch.mapping)
    valid = [row for row in previews if row.status == "valid"]
    try:
        with transaction.atomic():
            locked = CompanyImportBatch.objects.select_for_update().get(pk=batch.pk)
            if locked.status != CompanyImportBatch.Status.PREVIEWED or locked.imported_count:
                raise ImportFileError("Este lote não está disponível para execução.")
            for row in valid:
                company_values, location_values = _split_values(row.values)
                company = Company(**company_values)
                company.full_clean()
                company.save()
                CompanyImportItem.objects.create(
                    batch=locked, company=company, source_row=row.number
                )
                if location_values["label"] and location_values["address"]:
                    location = CustomerDeliveryLocation(company=company, **location_values)
                    location.full_clean()
                    location.save()
                    record_audit(
                        actor=actor,
                        action="company_import.delivery_location_created",
                        entity=location,
                        payload={
                            "batch_id": str(locked.pk),
                            "company_id": str(company.pk),
                            "source_row": row.number,
                        },
                    )
            locked.imported_count = len(valid)
            locked.executed_at = timezone.now()
            locked.status = CompanyImportBatch.Status.COMPLETED
            locked.final_message = f"{len(valid)} cliente(s) importado(s)."
            locked.save()
            record_audit(
                actor=actor,
                action="company_import.executed",
                entity=locked,
                payload={"imported": len(valid)},
            )
        return len(valid)
    except Exception as exc:
        CompanyImportBatch.objects.filter(pk=batch.pk).update(
            status=CompanyImportBatch.Status.FAILED,
            executed_at=timezone.now(),
            final_message="Falha crítica; nenhuma empresa foi importada.",
        )
        record_audit(
            actor=actor,
            action="company_import.failed",
            entity=batch,
            payload={"error_type": type(exc).__name__},
        )
        raise


def rollback_batch(batch: CompanyImportBatch, actor) -> int:
    blocked_message = ""
    count = 0
    with transaction.atomic():
        locked = CompanyImportBatch.objects.select_for_update().get(pk=batch.pk)
        allowed_statuses = {
            CompanyImportBatch.Status.COMPLETED,
            CompanyImportBatch.Status.ROLLBACK_BLOCKED,
        }
        if locked.status not in allowed_statuses:
            raise ImportFileError("Este lote não está disponível para rollback.")
        companies = [item.company for item in locked.items.select_related("company")]
        imported_location_ids = set(
            AuditEvent.objects.filter(
                action="company_import.delivery_location_created",
                payload__batch_id=str(locked.pk),
            ).values_list("entity_id", flat=True)
        )
        blocked = [
            company
            for company in companies
            if (
                company.orders.exists()
                or company.closings.exists()
                or company.customer_order_requests.exists()
                or company.portal_accesses.exists()
                or company.portal_access_requests.exists()
                or company.customer_delivery_locations.exclude(
                    pk__in=imported_location_ids
                ).exists()
            )
        ]
        if blocked:
            locked.status = CompanyImportBatch.Status.ROLLBACK_BLOCKED
            locked.final_message = "Rollback bloqueado por status ou vínculo operacional."
            locked.save(update_fields=("status", "final_message"))
            record_audit(
                actor=actor,
                action="company_import.rollback_blocked",
                entity=locked,
                payload={"blocked_count": len(blocked)},
            )
            blocked_message = locked.final_message
        else:
            count = len(companies)
            CustomerDeliveryLocation.objects.filter(
                pk__in=imported_location_ids,
                company__in=companies,
            ).delete()
            locked.items.all().delete()
            for company in companies:
                company.delete()
            locked.status = CompanyImportBatch.Status.ROLLED_BACK
            locked.rollback_by = actor
            locked.rollback_at = timezone.now()
            locked.final_message = f"Rollback concluído para {count} cliente(s)."
            locked.save()
            record_audit(
                actor=actor,
                action="company_import.rolled_back",
                entity=locked,
                payload={"removed": count, "locations_removed": len(imported_location_ids)},
            )
    if blocked_message:
        raise ImportFileError(blocked_message)
    return count

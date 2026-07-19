from __future__ import annotations

import re
from collections.abc import Iterable, Iterator


class PrivacyBlocked(ValueError):
    pass


EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?55\s*)?(?:\(?\d{2}\)?\s*)?9?\d{4}[-\s]?\d{4}(?!\d)")
DOCUMENT_PATTERN = re.compile(
    r"(?<!\d)(?:\d{3}[.\s-]?\d{3}[.\s-]?\d{3}[-\s]?\d{2}|"
    r"\d{2}[.\s-]?\d{3}[.\s-]?\d{3}[/\s-]?\d{4}[-\s]?\d{2})(?!\d)"
)
URL_PATTERN = re.compile(r"https?://\S+", re.IGNORECASE)
OPERATIONAL_REFERENCE_PATTERN = re.compile(
    r"\b(?:PED|SOL|EMP|PROD|COMP)-[A-Z0-9][A-Z0-9-]{3,}\b",
    re.IGNORECASE,
)
TEXT_KEYS = {
    "title",
    "summary",
    "action_suggested",
    "notes",
    "notes_sanitized",
    "anomalies",
}


def _replace_terms(value: str, terms: Iterable[str]) -> str:
    sanitized = value
    cleaned_terms = {term.strip() for term in terms if term and term.strip()}
    for term in sorted(cleaned_terms, key=len, reverse=True):
        sanitized = re.sub(re.escape(term), "[DADO_REMOVIDO]", sanitized, flags=re.IGNORECASE)
    return sanitized


def _mask_operational_references(value: str) -> str:
    return OPERATIONAL_REFERENCE_PATTERN.sub("[REF_OPERACIONAL]", value)


def sanitize_text(value: str, *, redaction_terms: Iterable[str] = ()) -> str:
    sanitized = value.strip()[:2000]
    sanitized = _replace_terms(sanitized, redaction_terms)
    sanitized = EMAIL_PATTERN.sub("[EMAIL_REMOVIDO]", sanitized)
    sanitized = PHONE_PATTERN.sub("[TELEFONE_REMOVIDO]", sanitized)
    sanitized = DOCUMENT_PATTERN.sub("[DOCUMENTO_REMOVIDO]", sanitized)
    sanitized = URL_PATTERN.sub("[URL_REMOVIDA]", sanitized)
    return re.sub(r"\s+", " ", sanitized).strip()


def _iter_reviewable_text(value: object, *, parent_key: str = "") -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _iter_reviewable_text(item, parent_key=str(key))
    elif isinstance(value, list):
        for item in value:
            yield from _iter_reviewable_text(item, parent_key=parent_key)
    elif isinstance(value, str) and parent_key in TEXT_KEYS:
        yield value


def assert_payload_safe(payload: dict, *, forbidden_terms: Iterable[str] = ()) -> None:
    text = _mask_operational_references("\n".join(_iter_reviewable_text(payload)))
    lowered = text.casefold()
    if EMAIL_PATTERN.search(text):
        raise PrivacyBlocked("email_detected")
    if PHONE_PATTERN.search(text):
        raise PrivacyBlocked("phone_detected")
    if DOCUMENT_PATTERN.search(text):
        raise PrivacyBlocked("document_detected")
    for term in forbidden_terms:
        cleaned = term.strip().casefold()
        if cleaned and cleaned in lowered:
            raise PrivacyBlocked("forbidden_term_detected")

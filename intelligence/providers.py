from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.conf import settings


class ProviderTransientError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class ProviderPermanentError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProviderResult:
    output: dict
    latency_ms: int
    prompt_tokens: int = 0
    output_tokens: int = 0


RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "maxLength": 180},
        "summary": {"type": "string", "maxLength": 900},
        "action_suggested": {"type": "string", "maxLength": 500},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["title", "summary", "action_suggested", "confidence"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Você é o supervisor operacional do Empório Pedidos.
Use somente as evidências sanitizadas recebidas. Não invente fatos, nomes ou valores.
Explique o risco ou resumo em português brasileiro, de forma objetiva e operacional.
Nunca ordene alteração automática de pedido, status, preço, fechamento ou faturamento.
Nunca proponha envio automático de WhatsApp, e-mail ou outra ação externa.
Retorne somente o JSON aderente ao schema fornecido.
"""


def _validated_output(value: dict) -> dict:
    required = {"title", "summary", "action_suggested", "confidence"}
    if not isinstance(value, dict) or set(value) != required:
        raise ProviderPermanentError("invalid_schema")
    if not all(isinstance(value[key], str) for key in required - {"confidence"}):
        raise ProviderPermanentError("invalid_schema")
    try:
        confidence = Decimal(str(value["confidence"]))
    except (InvalidOperation, TypeError) as exc:
        raise ProviderPermanentError("invalid_confidence") from exc
    if confidence < 0 or confidence > 1:
        raise ProviderPermanentError("invalid_confidence")
    return {
        "title": value["title"].strip()[:180],
        "summary": value["summary"].strip()[:900],
        "action_suggested": value["action_suggested"].strip()[:500],
        "confidence": float(confidence),
    }


class GeminiProvider:
    provider_name = "gemini"

    def generate(self, *, payload: dict, prompt_version: str) -> ProviderResult:
        api_key = settings.GEMINI_API_KEY.strip()
        if not api_key:
            raise ProviderPermanentError("api_key_not_configured")

        endpoint = settings.GEMINI_API_URL.format(model=settings.GEMINI_MODEL)
        prompt = (
            f"Versão do prompt: {prompt_version}\n"
            f"Instruções:\n{SYSTEM_PROMPT}\n"
            "Evidências sanitizadas:\n"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )
        body = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 700,
                "responseMimeType": "application/json",
                "responseJsonSchema": RESPONSE_SCHEMA,
            },
        }
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=settings.AI_TIMEOUT_SECONDS) as response:
                response_data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429 or 500 <= exc.code < 600:
                raise ProviderTransientError(f"http_{exc.code}") from None
            raise ProviderPermanentError(f"http_{exc.code}") from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ProviderTransientError("network_or_decode_error") from None

        try:
            parts = response_data["candidates"][0]["content"]["parts"]
            text = "".join(part.get("text", "") for part in parts)
            parsed = json.loads(text)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            raise ProviderPermanentError("invalid_provider_response") from None

        usage = response_data.get("usageMetadata", {})
        return ProviderResult(
            output=_validated_output(parsed),
            latency_ms=max(0, int((time.monotonic() - started) * 1000)),
            prompt_tokens=int(usage.get("promptTokenCount", 0) or 0),
            output_tokens=int(usage.get("candidatesTokenCount", 0) or 0),
        )

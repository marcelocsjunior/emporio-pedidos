from pathlib import Path

from django.conf import settings


def _read(path: str) -> str:
    return (Path(settings.BASE_DIR) / path).read_text(encoding="utf-8")


def test_assistant_counter_keeps_safe_width_at_320px():
    css = _read("static/css/intelligence.css")
    mobile_block = css.split("@media (max-width: 720px) {", maxsplit=1)[1]

    assert ".operational-assistant-heading > div:first-child" in mobile_block
    assert "min-width: 0;" in mobile_block
    assert ".assistant-total {\n    min-width: 86px;\n    flex: 0 0 auto;" in mobile_block


def test_assistant_panel_remains_navigation_only():
    template = _read("templates/orders/_operational_assistant.html")

    assert "Abrir solicitação" not in template or "<a class=\"button compact\"" in template
    assert "<form" not in template
    assert "Autorizar" not in template
    assert "Registrar saída" not in template

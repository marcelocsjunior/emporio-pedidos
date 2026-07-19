import pytest

from intelligence.privacy import PrivacyBlocked, assert_payload_safe


@pytest.mark.parametrize(
    "reference",
    (
        "PED-12345678",
        "SOL-2026-0041",
        "EMP-172FA96B",
        "PROD-12345678",
        "COMP-123456789012",
    ),
)
def test_operational_reference_is_not_classified_as_pii(reference):
    assert_payload_safe({"title": f"Registro {reference} requer atenção"})


def test_real_phone_remains_blocked_after_operational_reference_masking():
    with pytest.raises(PrivacyBlocked, match="phone_detected"):
        assert_payload_safe(
            {
                "title": "Pedido PED-12345678 requer atenção",
                "summary": "Confirmar pelo telefone (31) 99999-9999.",
            }
        )

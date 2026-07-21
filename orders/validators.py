from __future__ import annotations

import re

from django.core.exceptions import ValidationError


def digits_only(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def validate_numeric_text(value: str | None, *, label: str) -> None:
    raw = (value or "").strip()
    if not raw:
        return
    if re.search(r"[^0-9\s./-]", raw) or not digits_only(raw):
        raise ValidationError(f"{label} deve conter somente números e pontuação.")


def _all_digits_equal(value: str) -> bool:
    return bool(value) and len(set(value)) == 1


def _check_digit(numbers: list[int], weights: tuple[int, ...]) -> int:
    remainder = (
        sum(number * weight for number, weight in zip(numbers, weights, strict=True))
        % 11
    )
    return 0 if remainder < 2 else 11 - remainder


def validate_cpf(value: str) -> None:
    cpf = digits_only(value)
    if len(cpf) != 11 or _all_digits_equal(cpf):
        raise ValidationError("CPF inválido.")

    numbers = [int(character) for character in cpf]
    first = _check_digit(numbers[:9], tuple(range(10, 1, -1)))
    second = _check_digit(numbers[:10], tuple(range(11, 1, -1)))
    if numbers[9:] != [first, second]:
        raise ValidationError("CPF inválido.")


def validate_cnpj(value: str) -> None:
    cnpj = digits_only(value)
    if len(cnpj) != 14 or _all_digits_equal(cnpj):
        raise ValidationError("CNPJ inválido.")

    numbers = [int(character) for character in cnpj]
    first_weights = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    second_weights = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    first = _check_digit(numbers[:12], first_weights)
    second = _check_digit(numbers[:13], second_weights)
    if numbers[12:] != [first, second]:
        raise ValidationError("CNPJ inválido.")

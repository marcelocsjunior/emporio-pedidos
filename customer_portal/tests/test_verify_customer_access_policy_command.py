from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

pytestmark = pytest.mark.django_db
User = get_user_model()


@pytest.fixture(autouse=True)
def exact_policy(settings):
    settings.CUSTOMER_ACCESS_MANAGER_USERNAMES = ("angela", "suporte", "ti")


def test_verifier_accepts_support_absent_and_angela_password_change_pending():
    User.objects.create_user(
        username="angela",
        password="SenhaForte!2026",
        must_change_password=True,
    )
    User.objects.create_user(username="ti", password="SenhaForte!2026")
    before = User.objects.count()
    stdout = StringIO()

    call_command("verify_customer_access_policy", stdout=stdout)

    output = stdout.getvalue()
    assert "USER_ANGELA=ACTIVE;MUST_CHANGE_PASSWORD=1;BACKEND_AUTHORIZED=1" in output
    assert "USER_TI=ACTIVE;MUST_CHANGE_PASSWORD=0;BACKEND_AUTHORIZED=1" in output
    assert "SUPPORT_ACCOUNT=ABSENT_ALLOWED" in output
    assert "PASSWORD_REDIRECT_HTTP_NOT_USED=1; DATA_WRITES=ZERO" in output
    assert User.objects.count() == before


def test_verifier_reports_active_support_when_account_exists():
    User.objects.create_user(username="angela", password="SenhaForte!2026")
    User.objects.create_user(username="suporte", password="SenhaForte!2026")
    User.objects.create_user(username="ti", password="SenhaForte!2026")
    stdout = StringIO()

    call_command("verify_customer_access_policy", stdout=stdout)

    assert "SUPPORT_ACCOUNT=PRESENT_ACTIVE" in stdout.getvalue()


def test_verifier_rejects_missing_required_existing_account():
    User.objects.create_user(username="ti", password="SenhaForte!2026")

    with pytest.raises(CommandError, match="angela"):
        call_command("verify_customer_access_policy")

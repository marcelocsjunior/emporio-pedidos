import pytest


@pytest.fixture(autouse=True)
def preserve_existing_portal_test_modes(settings):
    settings.PUBLIC_ACCESS_REQUEST_ENABLED = True
    settings.CUSTOMER_ACCESS_MANAGER_USERNAMES = (
        "angela",
        "suporte",
        "ti",
        "operador",
        "operador-flag",
    )

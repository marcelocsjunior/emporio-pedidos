import pytest


@pytest.fixture(autouse=True)
def enable_public_access_for_existing_portal_tests(settings):
    settings.PUBLIC_ACCESS_REQUEST_ENABLED = True

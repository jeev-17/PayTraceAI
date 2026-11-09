import pytest


@pytest.fixture(autouse=True)
def configure_test_admin_key(monkeypatch):
    monkeypatch.setattr(
        "app.security.settings.admin_api_key",
        "test-admin-key",
    )

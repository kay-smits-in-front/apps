import pytest

import app as app_module


@pytest.fixture()
def client():
    app = app_module.app
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SECRET_KEY="test-secret-key-that-is-long-enough",
        SESSION_COOKIE_SECURE=False,
        TRUSTED_HOSTS=["localhost", "127.0.0.1"],
    )
    return app.test_client()


def test_login_page_loads_and_has_security_headers(client):
    response = client.get("/login")
    assert response.status_code == 200
    assert b"Welkom terug" in response.data
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


def test_dashboard_requires_authentication(client):
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_page_requires_authentication(client):
    response = client.get("/admin/users")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_health_endpoint_is_available(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json == {"status": "ok"}

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



def test_public_pages_do_not_expose_admin_email_or_password_hash(client):
    for path in ("/login", "/request-access"):
        response = client.get(path)
        assert response.status_code == 200
        assert b"kaysmits@icloud.com" not in response.data
        assert b"password_hash" not in response.data
        assert b"SECRET_KEY" not in response.data


def test_signup_password_hash_is_not_in_response(client):
    response = client.post(
        "/request-access",
        data={
            "email": "privacy-test@example.com",
            "password": "a-unique-test-password-123",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"password_hash" not in response.data
    assert b"a-unique-test-password-123" not in response.data

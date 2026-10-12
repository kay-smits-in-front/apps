import re

import pytest
from werkzeug.security import generate_password_hash

import app as app_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    app = app_module.app
    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'test.db'}",
        SECRET_KEY="test-secret-key-that-is-long-enough",
        SESSION_COOKIE_SECURE=False,
        TRUSTED_HOSTS=["localhost", "127.0.0.1"],
    )
    with app.app_context():
        app_module.db.drop_all()
        app_module.db.create_all()
        admin = app_module.User(
            email="kaysmits@icloud.com",
            password_hash=generate_password_hash("test-only-password"),
            approved=True,
            is_admin=True,
        )
        app_module.db.session.add(admin)
        app_module.db.session.commit()
    yield app.test_client()
    with app.app_context():
        app_module.db.session.remove()
        app_module.db.drop_all()


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

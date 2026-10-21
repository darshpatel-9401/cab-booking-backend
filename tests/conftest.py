import pytest
from fastapi.testclient import TestClient

from auth import get_current_user
from main import app

FAKE_USER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "email": "test@example.com",
}


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture
def authed_client():
    app.dependency_overrides[get_current_user] = lambda: FAKE_USER
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_current_user, None)
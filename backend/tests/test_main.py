from fastapi.testclient import TestClient

from timeline_api.main import app


def test_application_metadata_is_available_on_import() -> None:
    assert app.title == "Federated Patient Timeline API"
    assert app.version == "0.1.0"


def test_openapi_and_docs_are_available() -> None:
    with TestClient(app) as client:
        openapi_response = client.get("/openapi.json")
        docs_response = client.get("/docs")

    assert openapi_response.status_code == 200
    assert openapi_response.json()["info"]["title"] == "Federated Patient Timeline API"
    assert docs_response.status_code == 200
    assert "swagger-ui" in docs_response.text

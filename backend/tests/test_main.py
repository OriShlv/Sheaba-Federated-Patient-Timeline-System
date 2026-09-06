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
    schema = openapi_response.json()
    assert schema["info"]["title"] == "Federated Patient Timeline API"
    timeline_operation = schema["paths"]["/api/timeline"]["get"]
    parameter_names = {
        (parameter["in"], parameter["name"]) for parameter in timeline_operation["parameters"]
    }
    assert ("header", "X-User-Role") in parameter_names
    assert ("query", "types") in parameter_names
    responses = timeline_operation["responses"]
    assert "422" not in responses
    assert responses["206"]["content"]["application/json"] == {
        "schema": {"$ref": "#/components/schemas/TimelineResponse"},
        "example": {
            "parents": [],
            "standalone": [],
            "partial": True,
            "warning": "Unavailable sources: pacs",
        },
    }
    assert responses["400"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ValidationErrorResponse"
    }
    assert responses["400"]["content"]["application/json"]["example"]["detail"][0]["loc"] == [
        "query",
        "patientId",
    ]
    assert responses["500"]["content"]["application/json"] == {
        "schema": {"$ref": "#/components/schemas/InternalServerErrorResponse"},
        "example": {"detail": "Internal server error"},
    }
    assert docs_response.status_code == 200
    assert "swagger-ui" in docs_response.text

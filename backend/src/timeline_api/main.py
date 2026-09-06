from typing import cast

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from timeline_api.api.errors import (
    internal_server_error_response,
    request_validation_error_response,
)
from timeline_api.api.routes import router
from timeline_api.config import Settings
from timeline_api.logging import configure_logging
from timeline_api.resources import build_lifespan


def _without_timeline_422_response(schema: dict[str, object]) -> dict[str, object]:
    paths = cast(dict[str, object], schema["paths"])
    timeline_path = cast(dict[str, object], paths["/api/timeline"])
    operation = cast(dict[str, object], timeline_path["get"])
    responses = cast(dict[str, object], operation["responses"])

    updated_operation = {
        **operation,
        "responses": {
            status: response for status, response in responses.items() if status != "422"
        },
    }
    updated_timeline_path = {**timeline_path, "get": updated_operation}
    return {
        **schema,
        "paths": {**paths, "/api/timeline": updated_timeline_path},
    }


def create_app(settings: Settings) -> FastAPI:
    configure_logging(settings.log_level)
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=build_lifespan(settings),
    )
    application.include_router(router)
    application.add_exception_handler(RequestValidationError, request_validation_error_response)
    application.add_exception_handler(Exception, internal_server_error_response)

    default_openapi = application.openapi

    def openapi() -> dict[str, object]:
        return _without_timeline_422_response(cast(dict[str, object], default_openapi()))

    application.openapi = openapi  # type: ignore[method-assign]
    return application


app = create_app(Settings())

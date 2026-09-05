import asyncpg
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from timeline_api.api.routes import (
    postgres_error_response,
    request_validation_error_response,
    router,
)
from timeline_api.config import Settings
from timeline_api.logging import configure_logging
from timeline_api.resources import build_lifespan


def create_app(settings: Settings) -> FastAPI:
    configure_logging(settings.log_level)
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=build_lifespan(settings),
    )
    application.include_router(router)
    application.add_exception_handler(RequestValidationError, request_validation_error_response)
    application.add_exception_handler(asyncpg.PostgresError, postgres_error_response)
    return application


app = create_app(Settings())

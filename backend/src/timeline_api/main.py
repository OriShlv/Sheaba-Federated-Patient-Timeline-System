from fastapi import FastAPI

from timeline_api.config import Settings
from timeline_api.logging import configure_logging
from timeline_api.resources import build_lifespan


def create_app(settings: Settings) -> FastAPI:
    configure_logging(settings.log_level)
    return FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=build_lifespan(settings),
    )


app = create_app(Settings())

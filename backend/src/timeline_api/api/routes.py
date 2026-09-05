from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from timeline_api.adapters import RegistryAdapter
from timeline_api.api.models import TimelineResponse, to_timeline_response
from timeline_api.api.query import TimelineQueryParameters, to_timeline_query
from timeline_api.resources import get_resources
from timeline_api.services import TimelineService

router = APIRouter(prefix="/api")


def get_timeline_service(request: Request) -> TimelineService:
    registry_adapter = RegistryAdapter(get_resources(request.app).postgres_pool)
    return TimelineService(registry_adapter)


@router.get("/timeline", response_model=TimelineResponse)
async def get_timeline(
    query_parameters: Annotated[TimelineQueryParameters, Query()],
    service: Annotated[TimelineService, Depends(get_timeline_service)],
) -> TimelineResponse:
    result = await service.get_timeline(to_timeline_query(query_parameters))
    return to_timeline_response(result)


async def request_validation_error_response(
    _request: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise TypeError("request validation handler received an unexpected exception")
    return JSONResponse(
        status_code=400,
        content={"detail": jsonable_encoder(error.errors())},
    )


async def postgres_error_response(
    _request: Request,
    error: Exception,
) -> JSONResponse:
    if not isinstance(error, asyncpg.PostgresError):
        raise TypeError("PostgreSQL handler received an unexpected exception")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

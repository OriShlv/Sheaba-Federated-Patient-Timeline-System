from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from timeline_api.adapters import PacsAdapter, RegistryAdapter, VitalsAdapter
from timeline_api.api.errors import InternalServerErrorResponse, ValidationErrorResponse
from timeline_api.api.models import TimelineResponse, to_timeline_response
from timeline_api.api.query import TimelineQueryParameters, to_timeline_query
from timeline_api.resources import get_resources
from timeline_api.services import TimelineService, UserRole

router = APIRouter(prefix="/api")

PARTIAL_RESPONSE_EXAMPLE: dict[str, object] = {
    "parents": [],
    "standalone": [],
    "partial": True,
    "warning": "Unavailable sources: pacs",
}
VALIDATION_ERROR_EXAMPLE: dict[str, object] = {
    "detail": [
        {
            "type": "greater_than",
            "loc": ["query", "patientId"],
            "msg": "Input should be greater than 0",
            "input": "0",
        }
    ]
}
INTERNAL_SERVER_ERROR_EXAMPLE: dict[str, object] = {
    "detail": "Internal server error",
}


def get_timeline_service(request: Request) -> TimelineService:
    resources = get_resources(request.app)
    settings = resources.settings
    return TimelineService(
        RegistryAdapter(resources.postgres_pool, settings.registry_timeout_seconds),
        PacsAdapter(
            resources.mongo_client,
            settings.mongo_database,
            settings.pacs_timeout_seconds,
        ),
        VitalsAdapter(resources.http_client, settings.vitals_timeout_seconds),
    )


@router.get(
    "/timeline",
    response_model=TimelineResponse,
    response_model_exclude_none=True,
    responses={
        206: {
            "model": TimelineResponse,
            "description": "Timeline returned with one or more unavailable sources",
            "content": {"application/json": {"example": PARTIAL_RESPONSE_EXAMPLE}},
        },
        400: {
            "model": ValidationErrorResponse,
            "description": "Request validation failed",
            "content": {"application/json": {"example": VALIDATION_ERROR_EXAMPLE}},
        },
        500: {
            "model": InternalServerErrorResponse,
            "description": "Unexpected internal failure",
            "content": {"application/json": {"example": INTERNAL_SERVER_ERROR_EXAMPLE}},
        },
    },
)
async def get_timeline(
    query_parameters: Annotated[TimelineQueryParameters, Query()],
    role: Annotated[UserRole, Header(alias="X-User-Role")],
    response: Response,
    service: Annotated[TimelineService, Depends(get_timeline_service)],
) -> TimelineResponse:
    result = await service.get_timeline(to_timeline_query(query_parameters, role))
    if result.partial:
        response.status_code = status.HTTP_206_PARTIAL_CONTENT
    return to_timeline_response(result)

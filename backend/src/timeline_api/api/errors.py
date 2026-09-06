import logging
from typing import Literal

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from timeline_api.domain.models import DomainModel
from timeline_api.logging import OperationalEvent

LOGGER = logging.getLogger(__name__)


class ValidationErrorItem(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    type: str
    loc: tuple[str | int, ...]
    msg: str


class ValidationErrorResponse(DomainModel):
    detail: tuple[ValidationErrorItem, ...]


class InternalServerErrorResponse(DomainModel):
    detail: Literal["Internal server error"]


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


async def internal_server_error_response(
    _request: Request,
    _error: Exception,
) -> JSONResponse:
    LOGGER.error(
        "Unhandled timeline request failure",
        extra={"operational_event": OperationalEvent.TIMELINE_REQUEST_FAILED},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )

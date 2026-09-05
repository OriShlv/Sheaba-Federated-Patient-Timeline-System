import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from timeline_api.config import Settings
from timeline_api.main import create_app
from timeline_api.resources import get_resources


def test_lifespan_creates_one_lazy_resource_set_and_closes_it() -> None:
    app = create_app(Settings())

    with TestClient(app):
        resources = get_resources(app)

        assert get_resources(app) is resources
        assert resources.postgres_pool.get_min_size() == 0
        assert not resources.http_client.is_closed

    assert resources.http_client.is_closed
    with pytest.raises(RuntimeError, match="outside the lifespan"):
        get_resources(app)


def test_resources_are_unavailable_before_startup() -> None:
    with pytest.raises(RuntimeError, match="outside the lifespan"):
        get_resources(FastAPI())

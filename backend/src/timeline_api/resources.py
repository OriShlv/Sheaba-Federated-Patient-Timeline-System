from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass

import asyncpg
import httpx
from fastapi import FastAPI
from pymongo import AsyncMongoClient

from timeline_api.config import Settings


@dataclass(frozen=True, slots=True)
class AppResources:
    settings: Settings
    postgres_pool: asyncpg.Pool
    mongo_client: AsyncMongoClient[dict[str, object]]
    http_client: httpx.AsyncClient


async def create_resources(settings: Settings) -> AppResources:
    postgres_pool = await asyncpg.create_pool(
        dsn=str(settings.postgres_dsn),
        min_size=0,
        max_size=settings.postgres_pool_max_size,
    )
    mongo_client = AsyncMongoClient[dict[str, object]](
        str(settings.mongo_uri),
        tz_aware=True,
    )
    http_client = httpx.AsyncClient(base_url=str(settings.vitals_base_url))

    return AppResources(
        settings=settings,
        postgres_pool=postgres_pool,
        mongo_client=mongo_client,
        http_client=http_client,
    )


async def close_resources(resources: AppResources) -> None:
    await resources.http_client.aclose()
    await resources.mongo_client.close()
    await resources.postgres_pool.close()


def get_resources(app: FastAPI) -> AppResources:
    resources = getattr(app.state, "resources", None)
    if not isinstance(resources, AppResources):
        raise RuntimeError("application resources are unavailable outside the lifespan")
    return resources


type Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def build_lifespan(settings: Settings) -> Lifespan:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resources = await create_resources(settings)
        app.state.resources = resources
        try:
            yield
        finally:
            try:
                await close_resources(resources)
            finally:
                del app.state.resources

    return lifespan

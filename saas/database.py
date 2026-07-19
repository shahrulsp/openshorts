from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from saas.config import load_saas_settings


Base = declarative_base()

_engine = None
_sessionmaker = None


def init_engine():
    global _engine, _sessionmaker

    settings = load_saas_settings()
    if not settings.database_url:
        raise RuntimeError("SAAS_DATABASE_URL or DATABASE_URL is required when SaaS is enabled")

    _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker():
    if _sessionmaker is None:
        init_engine()
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session

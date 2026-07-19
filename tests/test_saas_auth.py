import asyncio
from collections.abc import AsyncIterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from app import app
from saas.auth import hash_password
from saas.database import Base, get_db
from saas.models import User, Workspace


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def db_sessionmaker(tmp_path):
    db_file = tmp_path / "saas-auth.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    asyncio.run(_create_schema(engine))
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield sessionmaker
    finally:
        asyncio.run(engine.dispose())


@pytest.fixture
def client(db_sessionmaker):
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with db_sessionmaker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()


@pytest.fixture
def seeded_owner(db_sessionmaker):
    async def seed() -> dict[str, str]:
        async with db_sessionmaker() as session:
            workspace = Workspace(slug="acme", name="Acme", plan="free")
            session.add(workspace)
            await session.flush()

            user = User(
                workspace_id=workspace.id,
                email="owner@example.com",
                full_name="Owner",
                role="owner",
                password_hash=hash_password("secret123"),
            )
            session.add(user)
            await session.commit()

            return {
                "workspace_id": str(workspace.id),
                "workspace_slug": workspace.slug,
                "email": user.email,
            }

    return asyncio.run(seed())


def test_signup_returns_bearer_token(client):
    response = client.post(
        "/api/saas/auth/signup",
        json={
            "workspace_name": "Acme Studio",
            "full_name": "Owner Example",
            "email": "owner@example.com",
            "password": "secret123",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "owner@example.com"
    assert body["user"]["role"] == "owner"
    assert body["workspace"]["name"] == "Acme Studio"
    assert body["workspace"]["slug"] == "acme-studio"


def test_login_returns_bearer_token(client, seeded_owner):
    response = client.post(
        "/api/saas/auth/login",
        json={
            "email": "owner@example.com",
            "password": "secret123",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == seeded_owner["email"]
    assert body["workspace"]["slug"] == seeded_owner["workspace_slug"]


def test_me_requires_authentication(client):
    response = client.get("/api/saas/me")

    assert response.status_code == 401
    assert response.json()["detail"] == "Authentication required"


def test_me_returns_current_user_and_workspace(client, seeded_owner):
    login_response = client.post(
        "/api/saas/auth/login",
        json={
            "email": "owner@example.com",
            "password": "secret123",
        },
    )
    token = login_response.json()["access_token"]

    response = client.get(
        "/api/saas/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == seeded_owner["email"]
    assert body["user"]["role"] == "owner"
    assert body["workspace"]["id"] == seeded_owner["workspace_id"]
    assert body["workspace"]["slug"] == seeded_owner["workspace_slug"]
    assert body["workspace"]["plan"] == "free"

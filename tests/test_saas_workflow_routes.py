import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from saas.models import Asset
from saas.auth import CurrentSession, get_current_session
from saas.database import Base, get_db
from saas.models import Job, Project, User, Workspace
from saas.routes_workflow import router as workflow_router
import saas.routes_workflow as workflow_module


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
def db_sessionmaker(tmp_path):
    db_file = tmp_path / "saas-workflow-routes.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    asyncio.run(_create_schema(engine))
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        yield sessionmaker
    finally:
        asyncio.run(engine.dispose())


@pytest.fixture
def seeded_context(db_sessionmaker):
    async def seed() -> dict[str, uuid.UUID]:
        async with db_sessionmaker() as session:
            workspace = Workspace(slug="acme", name="Acme", plan="free")
            other_workspace = Workspace(slug="beta", name="Beta", plan="pro")
            session.add_all([workspace, other_workspace])
            await session.flush()

            user = User(
                workspace_id=workspace.id,
                email="owner@example.com",
                full_name="Owner",
                role="owner",
                password_hash="unused",
            )
            session.add(user)
            await session.commit()

            return {
                "user_id": user.id,
                "workspace_id": workspace.id,
                "other_workspace_id": other_workspace.id,
            }

    return asyncio.run(seed())


@pytest.fixture
def client(db_sessionmaker, seeded_context):
    app = FastAPI()
    app.include_router(workflow_router)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with db_sessionmaker() as session:
            yield session

    async def override_get_current_session() -> CurrentSession:
        async with db_sessionmaker() as session:
            user = await session.get(User, seeded_context["user_id"])
            workspace = await session.get(Workspace, seeded_context["workspace_id"])
            assert user is not None
            assert workspace is not None
            return CurrentSession(user=user, workspace=workspace)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_session] = override_get_current_session
    test_client = TestClient(app)
    try:
        yield test_client
    finally:
        test_client.close()
        app.dependency_overrides.clear()


def test_create_project_route_returns_draft_project(client):
    response = client.post(
        "/api/saas/projects",
        json={
            "kind": "clips",
            "title": "  Launch Cut  ",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["kind"] == "clips"
    assert body["title"] == "Launch Cut"
    assert body["status"] == "draft"
    assert uuid.UUID(body["workspace_id"])
    assert body["created_at"]


def test_list_routes_return_only_current_workspace_projects_and_jobs(client):
    first = client.post(
        "/api/saas/projects/with-job",
        json={
            "project_kind": "clips",
            "job_kind": "render",
            "title": "Launch Cut",
            "payload": {"source": "asset-1"},
        },
    )
    second = client.post(
        "/api/saas/projects/with-job",
        json={
            "project_kind": "ugc",
            "job_kind": "publish",
            "title": "Creator Cut",
            "payload": {"source": "asset-2"},
        },
    )

    assert first.status_code == 201
    assert second.status_code == 201

    projects_response = client.get("/api/saas/projects")
    jobs_response = client.get("/api/saas/jobs")

    assert projects_response.status_code == 200
    assert jobs_response.status_code == 200

    projects = projects_response.json()["projects"]
    jobs = jobs_response.json()["jobs"]

    assert {project["title"] for project in projects} == {"Creator Cut", "Launch Cut"}
    assert {job["kind"] for job in jobs} == {"publish", "render"}
    assert all(project["status"] == "queued" for project in projects)
    assert all(job["status"] == "queued" for job in jobs)


def test_project_detail_route_returns_project_with_related_jobs(client):
    create_response = client.post(
        "/api/saas/projects/with-job",
        json={
            "project_kind": "clips",
            "job_kind": "render",
            "title": "Launch Cut",
            "payload": {"source": "asset-1"},
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    project_id = created["project"]["id"]

    queue_response = client.post(
        f"/api/saas/projects/{project_id}/jobs",
        json={
            "kind": "publish",
            "payload": {"destination": "youtube"},
        },
    )
    assert queue_response.status_code == 201

    detail_response = client.get(f"/api/saas/projects/{project_id}")
    assert detail_response.status_code == 200

    detail = detail_response.json()
    assert detail["project"]["id"] == project_id
    assert {job["kind"] for job in detail["jobs"]} == {"render", "publish"}
    assert all(job["project_id"] == project_id for job in detail["jobs"])


def test_retry_route_requeues_failed_job_under_same_project(client):
    create_response = client.post(
        "/api/saas/projects/with-job",
        json={
            "project_kind": "clips",
            "job_kind": "render",
            "title": "Launch Cut",
            "payload": {"source_type": "url", "source_url": "https://example.com/video"},
        },
    )
    assert create_response.status_code == 201
    created = create_response.json()
    project_id = created["project"]["id"]
    job_id = created["job"]["id"]

    assert client.post(f"/api/saas/jobs/{job_id}/start", json={}).status_code == 200
    assert client.post(
        f"/api/saas/jobs/{job_id}/fail",
        json={"error_text": "renderer unavailable"},
    ).status_code == 200

    retry_response = client.post(
        f"/api/saas/jobs/{job_id}/retry",
        json={"legacy_job_id": "legacy-retry-123"},
    )
    assert retry_response.status_code == 201
    retried = retry_response.json()
    assert retried["project_id"] == project_id
    assert retried["status"] == "queued"
    assert retried["payload"]["retry_of_job_id"] == job_id
    assert retried["payload"]["legacy_job_id"] == "legacy-retry-123"

    detail_response = client.get(f"/api/saas/projects/{project_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["project"]["status"] == "queued"
    assert {job["id"] for job in detail["jobs"]} == {job_id, retried["id"]}


def test_retry_route_updates_source_asset_id_when_provided(client):
    create_response = client.post(
        "/api/saas/projects/with-job",
        json={
            "project_kind": "clips",
            "job_kind": "render",
            "title": "Launch Cut",
            "payload": {"source_type": "file", "source_name": "demo.mp4"},
        },
    )
    created = create_response.json()
    job_id = created["job"]["id"]

    assert client.post(f"/api/saas/jobs/{job_id}/start", json={}).status_code == 200
    assert client.post(
        f"/api/saas/jobs/{job_id}/fail",
        json={"error_text": "renderer unavailable"},
    ).status_code == 200

    asset_id = str(uuid.uuid4())
    retry_response = client.post(
        f"/api/saas/jobs/{job_id}/retry",
        json={"legacy_job_id": "legacy-retry-123", "source_asset_id": asset_id},
    )

    assert retry_response.status_code == 201
    retried = retry_response.json()
    assert retried["payload"]["source_asset_id"] == asset_id


def test_asset_content_route_returns_workspace_owned_file(client, db_sessionmaker, seeded_context, tmp_path, monkeypatch):
    asset_file = tmp_path / "demo.mp4"
    asset_file.write_bytes(b"demo-video")

    monkeypatch.setattr(workflow_module, "resolve_source_asset_path", lambda storage_key: str(asset_file))

    async def seed_asset() -> str:
        async with db_sessionmaker() as session:
            asset = Asset(
                workspace_id=seeded_context["workspace_id"],
                storage_key="acme/demo.mp4",
                mime_type="video/mp4",
                size_bytes=asset_file.stat().st_size,
                kind="source-upload",
            )
            session.add(asset)
            await session.commit()
            return str(asset.id)

    asset_id = asyncio.run(seed_asset())

    response = client.get(f"/api/saas/assets/{asset_id}/content")
    assert response.status_code == 200
    assert response.content == b"demo-video"
    assert response.headers["content-type"] == "video/mp4"


def test_workflow_routes_cover_create_queue_start_progress_and_complete(client, db_sessionmaker, seeded_context):
    create_response = client.post(
        "/api/saas/projects/with-job",
        json={
            "project_kind": "clips",
            "job_kind": "render",
            "title": "Launch Cut",
            "payload": {"source": "asset-1"},
        },
    )

    assert create_response.status_code == 201
    created = create_response.json()
    project_id = created["project"]["id"]
    job_id = created["job"]["id"]

    queue_response = client.post(
        f"/api/saas/projects/{project_id}/jobs",
        json={
            "kind": "publish",
            "payload": {"destination": "youtube"},
        },
    )
    assert queue_response.status_code == 201
    queued_job = queue_response.json()
    assert queued_job["project_id"] == project_id
    assert queued_job["status"] == "queued"

    started_at = datetime(2026, 7, 19, 14, 0, tzinfo=timezone.utc).isoformat()
    start_response = client.post(
        f"/api/saas/jobs/{job_id}/start",
        json={"started_at": started_at},
    )
    assert start_response.status_code == 200
    assert start_response.json()["status"] == "processing"
    assert start_response.json()["attempts"] == 1

    progress_response = client.post(
        f"/api/saas/jobs/{job_id}/progress",
        json={"progress": 65},
    )
    assert progress_response.status_code == 200
    assert progress_response.json()["progress"] == 65

    finished_at = datetime(2026, 7, 19, 14, 5, tzinfo=timezone.utc).isoformat()
    complete_response = client.post(
        f"/api/saas/jobs/{job_id}/complete",
        json={
            "result_payload": {"output": "asset-2"},
            "finished_at": finished_at,
        },
    )
    assert complete_response.status_code == 200
    completed = complete_response.json()
    assert completed["status"] == "completed"
    assert completed["progress"] == 100
    assert completed["result"] == {"output": "asset-2"}

    restart_response = client.post(f"/api/saas/jobs/{job_id}/start", json={})
    assert restart_response.status_code == 409
    assert restart_response.json()["detail"] == "Job state conflict: completed"

    async def verify_state() -> None:
        async with db_sessionmaker() as session:
            project = await session.get(Project, uuid.UUID(project_id))
            job = await session.get(Job, uuid.UUID(job_id))

            assert project is not None
            assert job is not None
            assert project.workspace_id == seeded_context["workspace_id"]
            assert project.status == "completed"
            assert job.status == "completed"
            assert job.progress == 100
            assert job.result == {"output": "asset-2"}

    asyncio.run(verify_state())


def test_fail_job_route_marks_project_failed(client, db_sessionmaker):
    create_response = client.post(
        "/api/saas/projects/with-job",
        json={
            "project_kind": "ugc",
            "job_kind": "render",
            "title": "Creator Cut",
            "payload": {"source": "asset-9"},
        },
    )
    job_id = create_response.json()["job"]["id"]
    project_id = create_response.json()["project"]["id"]

    assert client.post(f"/api/saas/jobs/{job_id}/start", json={}).status_code == 200

    fail_response = client.post(
        f"/api/saas/jobs/{job_id}/fail",
        json={"error_text": "renderer unavailable"},
    )

    assert fail_response.status_code == 200
    failed = fail_response.json()
    assert failed["status"] == "failed"
    assert failed["error_text"] == "renderer unavailable"

    async def verify_state() -> None:
        async with db_sessionmaker() as session:
            project = await session.get(Project, uuid.UUID(project_id))
            job = await session.get(Job, uuid.UUID(job_id))

            assert project is not None
            assert job is not None
            assert project.status == "failed"
            assert job.status == "failed"

    asyncio.run(verify_state())


def test_queue_job_route_rejects_foreign_workspace_project(client, db_sessionmaker, seeded_context):
    async def seed_foreign_project() -> uuid.UUID:
        async with db_sessionmaker() as session:
            project = Project(
                workspace_id=seeded_context["other_workspace_id"],
                kind="clips",
                title="Foreign Campaign",
                status="draft",
            )
            session.add(project)
            await session.commit()
            return project.id

    foreign_project_id = asyncio.run(seed_foreign_project())

    response = client.post(
        f"/api/saas/projects/{foreign_project_id}/jobs",
        json={
            "kind": "render",
            "payload": {"source": "asset-3"},
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Project not found"

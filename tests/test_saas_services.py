import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from saas.database import Base
from saas.repositories import JobRepository, ProjectRepository, WorkspaceRepository
from saas.services import (
    AuthService,
    InvalidCredentialsError,
    InvalidJobProgressError,
    JobStateConflictError,
    ProjectNotFoundError,
    UserAlreadyExistsError,
    WorkflowService,
    slugify_workspace_name,
)


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def test_slugify_workspace_name_handles_empty_and_punctuation():
    assert slugify_workspace_name("Acme Studio") == "acme-studio"
    assert slugify_workspace_name("!!!") == "workspace"


def test_auth_service_signup_owner_uses_unique_slug_and_normalizes_identity(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-signup.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            service = AuthService(session)
            first = await service.signup_owner(
                workspace_name="Acme Studio",
                full_name="Owner One",
                email="OWNER@EXAMPLE.COM",
                password="secret123",
            )
            second = await service.signup_owner(
                workspace_name="Acme Studio",
                full_name="Owner Two",
                email="owner2@example.com",
                password="secret123",
            )

            assert first.workspace.slug == "acme-studio"
            assert second.workspace.slug == "acme-studio-2"
            assert first.user.email == "owner@example.com"
            assert second.workspace.plan == "free"
            assert first.access_token
            assert second.access_token

        await engine.dispose()

    asyncio.run(scenario())


def test_auth_service_signup_owner_rolls_back_when_token_creation_fails(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-rollback.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            service = AuthService(
                session,
                token_issuer=lambda _user_id, _workspace_id: (_ for _ in ()).throw(RuntimeError("boom")),
            )
            with pytest.raises(RuntimeError, match="boom"):
                await service.signup_owner(
                    workspace_name="Acme Studio",
                    full_name="Owner Example",
                    email="owner@example.com",
                    password="secret123",
                )

        async with sessionmaker() as session:
            service = AuthService(session)
            with pytest.raises(InvalidCredentialsError):
                await service.authenticate(email="owner@example.com", password="secret123")

        await engine.dispose()

    asyncio.run(scenario())


def test_auth_service_rejects_duplicate_email_and_invalid_password(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-auth.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            service = AuthService(session)
            await service.signup_owner(
                workspace_name="Acme Studio",
                full_name="Owner Example",
                email="owner@example.com",
                password="secret123",
            )

        async with sessionmaker() as session:
            service = AuthService(session)
            with pytest.raises(UserAlreadyExistsError):
                await service.signup_owner(
                    workspace_name="Acme Studio",
                    full_name="Owner Example",
                    email="owner@example.com",
                    password="secret123",
                )

            with pytest.raises(InvalidCredentialsError):
                await service.authenticate(email="owner@example.com", password="wrong-pass")

            result = await service.authenticate(email="OWNER@example.com", password="secret123")
            assert result.user.email == "owner@example.com"
            assert result.workspace.slug == "acme-studio"
            assert result.access_token

        await engine.dispose()

    asyncio.run(scenario())


def test_workflow_service_create_project_job_creates_linked_records(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-project-job.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            workspace = await workspaces.create(slug="acme", name="Acme")
            await session.commit()

        async with sessionmaker() as session:
            service = WorkflowService(session)
            created = await service.create_project_job(
                workspace_id=workspace.id,
                project_kind="clips",
                job_kind="render",
                title="  Launch Cut  ",
                payload={"source": "asset-1"},
            )

            assert created.project.workspace_id == workspace.id
            assert created.project.title == "Launch Cut"
            assert created.project.status == "queued"
            assert created.job.workspace_id == workspace.id
            assert created.job.project_id == created.project.id
            assert created.job.kind == "render"
            assert created.job.status == "queued"
            assert created.job.payload == {"source": "asset-1"}

        async with sessionmaker() as session:
            projects = ProjectRepository(session)
            jobs = JobRepository(session)
            reloaded_project = await projects.get(created.project.id)
            reloaded_job = await jobs.get(created.job.id)

            assert reloaded_project is not None
            assert reloaded_project.status == "queued"
            assert reloaded_job is not None
            assert reloaded_job.project_id == created.project.id
            assert reloaded_job.payload == {"source": "asset-1"}

        await engine.dispose()

    asyncio.run(scenario())


def test_workflow_service_lists_workspace_projects_and_jobs_newest_first(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-listing.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            acme = await workspaces.create(slug="acme", name="Acme")
            beta = await workspaces.create(slug="beta", name="Beta")
            await session.commit()

        async with sessionmaker() as session:
            service = WorkflowService(session)
            first = await service.create_project_job(
                workspace_id=acme.id,
                project_kind="clips",
                job_kind="render",
                title="First",
                payload={"source": "asset-1"},
            )
            second = await service.create_project_job(
                workspace_id=acme.id,
                project_kind="clips",
                job_kind="publish",
                title="Second",
                payload={"source": "asset-2"},
            )
            await service.create_project_job(
                workspace_id=beta.id,
                project_kind="ugc",
                job_kind="render",
                title="Foreign",
                payload={"source": "asset-9"},
            )

            projects = await service.list_projects(workspace_id=acme.id)
            jobs = await service.list_jobs(workspace_id=acme.id)

            assert {project.id for project in projects} == {second.project.id, first.project.id}
            assert {job.id for job in jobs} == {second.job.id, first.job.id}
            assert all(project.workspace_id == acme.id for project in projects)
            assert all(job.workspace_id == acme.id for job in jobs)

        await engine.dispose()

    asyncio.run(scenario())


def test_workflow_service_returns_project_detail_with_workspace_scoped_jobs(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-project-detail.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            acme = await workspaces.create(slug="acme", name="Acme")
            beta = await workspaces.create(slug="beta", name="Beta")
            await session.commit()

        async with sessionmaker() as session:
            service = WorkflowService(session)
            created = await service.create_project_job(
                workspace_id=acme.id,
                project_kind="clips",
                job_kind="render",
                title="Launch Cut",
                payload={"source": "asset-1"},
            )
            await service.queue_job(
                workspace_id=acme.id,
                project_id=created.project.id,
                kind="publish",
                payload={"source": "asset-2"},
            )
            await service.create_project_job(
                workspace_id=beta.id,
                project_kind="ugc",
                job_kind="render",
                title="Foreign",
                payload={"source": "asset-9"},
            )

            detail = await service.get_project_detail(
                workspace_id=acme.id,
                project_id=created.project.id,
            )

            assert detail.project.id == created.project.id
            assert all(job.workspace_id == acme.id for job in detail.jobs)
            assert {job.kind for job in detail.jobs} == {"render", "publish"}

        await engine.dispose()

    asyncio.run(scenario())


def test_workflow_service_retry_job_requeues_failed_job_under_same_project(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-retry.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            workspace = await workspaces.create(slug="acme", name="Acme")
            await session.commit()

        async with sessionmaker() as session:
            service = WorkflowService(session)
            created = await service.create_project_job(
                workspace_id=workspace.id,
                project_kind="clips",
                job_kind="render",
                title="Launch Cut",
                payload={"source_type": "url", "source_url": "https://example.com/video"},
            )
            await service.start_job(workspace_id=workspace.id, job_id=created.job.id)
            await service.fail_job(
                workspace_id=workspace.id,
                job_id=created.job.id,
                error_text="network timeout",
            )

            retried = await service.retry_job(
                workspace_id=workspace.id,
                job_id=created.job.id,
                legacy_job_id="legacy-retry-123",
            )
            detail = await service.get_project_detail(workspace_id=workspace.id, project_id=created.project.id)

            assert retried.project_id == created.project.id
            assert retried.status == "queued"
            assert retried.payload["retry_of_job_id"] == str(created.job.id)
            assert retried.payload["legacy_job_id"] == "legacy-retry-123"
            assert detail.project.status == "queued"
            assert {job.id for job in detail.jobs} == {created.job.id, retried.id}

        await engine.dispose()

    asyncio.run(scenario())


def test_workflow_service_queue_job_rejects_cross_workspace_project_access(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-project-scope.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            projects = ProjectRepository(session)

            acme = await workspaces.create(slug="acme", name="Acme")
            beta = await workspaces.create(slug="beta", name="Beta")
            beta_project = await projects.create(workspace_id=beta.id, kind="ugc", title="Beta Campaign")
            await session.commit()

        async with sessionmaker() as session:
            service = WorkflowService(session)
            with pytest.raises(ProjectNotFoundError):
                await service.queue_job(
                    workspace_id=acme.id,
                    project_id=beta_project.id,
                    kind="render",
                    payload={"source": "asset-1"},
                )

        async with sessionmaker() as session:
            jobs = JobRepository(session)
            assert await jobs.list_for_workspace(acme.id) == []
            assert await jobs.list_for_workspace(beta.id) == []

        await engine.dispose()

    asyncio.run(scenario())


def test_workflow_service_job_lifecycle_updates_progress_and_project_status(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-services-job-lifecycle.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        started_at = datetime(2026, 7, 19, 13, 0, tzinfo=timezone.utc)
        finished_at = datetime(2026, 7, 19, 13, 5, tzinfo=timezone.utc)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            workspace = await workspaces.create(slug="acme", name="Acme")
            await session.commit()

        async with sessionmaker() as session:
            service = WorkflowService(session)
            created = await service.create_project_job(
                workspace_id=workspace.id,
                project_kind="clips",
                job_kind="render",
                title="Launch Cut",
                payload={"source": "asset-1"},
            )
            started_job = await service.start_job(
                workspace_id=workspace.id,
                job_id=created.job.id,
                started_at=started_at,
            )
            assert started_job.status == "processing"
            assert started_job.attempts == 1

            in_progress_job = await service.update_job_progress(
                workspace_id=workspace.id,
                job_id=created.job.id,
                progress=55,
            )
            assert in_progress_job.progress == 55

            completed_job = await service.complete_job(
                workspace_id=workspace.id,
                job_id=created.job.id,
                result_payload={"output": "asset-2"},
                finished_at=finished_at,
            )
            assert completed_job.status == "completed"
            assert completed_job.progress == 100
            assert completed_job.result == {"output": "asset-2"}

            with pytest.raises(InvalidJobProgressError):
                await service.update_job_progress(
                    workspace_id=workspace.id,
                    job_id=created.job.id,
                    progress=101,
                )

            with pytest.raises(JobStateConflictError):
                await service.start_job(workspace_id=workspace.id, job_id=created.job.id)

        async with sessionmaker() as session:
            projects = ProjectRepository(session)
            jobs = JobRepository(session)
            reloaded_project = await projects.get(created.project.id)
            reloaded_job = await jobs.get(created.job.id)

            assert reloaded_project is not None
            assert reloaded_project.status == "completed"
            assert reloaded_job is not None
            assert reloaded_job.status == "completed"
            assert reloaded_job.progress == 100
            assert reloaded_job.result == {"output": "asset-2"}
            assert reloaded_job.started_at == started_at.replace(tzinfo=None)
            assert reloaded_job.finished_at == finished_at.replace(tzinfo=None)

        await engine.dispose()

    asyncio.run(scenario())

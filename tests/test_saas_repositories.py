import asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from saas.database import Base
from saas.repositories import JobRepository, ProjectRepository, UserRepository, WorkspaceRepository


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def test_workspace_repository_create_flushes_without_committing(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-repositories-flush.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            workspace = await workspaces.create(slug="acme", name="Acme")
            workspace_id = workspace.id
            await session.rollback()

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            assert await workspaces.get(workspace_id) is None

        await engine.dispose()

    asyncio.run(scenario())


def test_user_and_project_repositories_scope_records_to_workspace(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-repositories-scope.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            users = UserRepository(session)
            projects = ProjectRepository(session)

            acme = await workspaces.create(slug="acme", name="Acme")
            beta = await workspaces.create(slug="beta", name="Beta")

            await users.create(
                workspace_id=acme.id,
                email="owner@acme.test",
                full_name="Acme Owner",
                role="owner",
                password_hash="hash-1",
            )
            await users.create(
                workspace_id=beta.id,
                email="owner@beta.test",
                full_name="Beta Owner",
                role="owner",
                password_hash="hash-2",
            )

            project = await projects.create(
                workspace_id=acme.id,
                kind="clips",
                title="Launch Cut",
            )
            await projects.create(
                workspace_id=beta.id,
                kind="ugc",
                title="Beta Campaign",
            )
            await projects.set_status(project, status="processing")
            await session.commit()

        async with sessionmaker() as session:
            users = UserRepository(session)
            projects = ProjectRepository(session)

            acme_users = await users.list_for_workspace(acme.id)
            acme_projects = await projects.list_for_workspace(acme.id)
            reloaded_project = await projects.get(project.id)

            assert [user.email for user in acme_users] == ["owner@acme.test"]
            assert [item.title for item in acme_projects] == ["Launch Cut"]
            assert reloaded_project is not None
            assert reloaded_project.status == "processing"

        await engine.dispose()

    asyncio.run(scenario())


def test_job_repository_updates_status_and_result_fields(tmp_path):
    async def scenario() -> None:
        db_file = tmp_path / "saas-repositories-jobs.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        started_at = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)
        finished_at = datetime(2026, 7, 19, 12, 5, tzinfo=timezone.utc)

        async with sessionmaker() as session:
            workspaces = WorkspaceRepository(session)
            projects = ProjectRepository(session)
            jobs = JobRepository(session)

            workspace = await workspaces.create(slug="acme", name="Acme")
            project = await projects.create(workspace_id=workspace.id, kind="clips", title="Launch Cut")
            job = await jobs.create(
                workspace_id=workspace.id,
                project_id=project.id,
                kind="render",
                payload={"source": "asset-1"},
            )
            await jobs.update_status(
                job,
                status="completed",
                progress=100,
                result_payload={"output": "asset-2"},
                started_at=started_at,
                finished_at=finished_at,
                attempts=1,
            )
            await session.commit()

        async with sessionmaker() as session:
            jobs = JobRepository(session)
            workspace_jobs = await jobs.list_for_workspace(workspace.id)
            reloaded_job = await jobs.get(job.id)

            assert [item.kind for item in workspace_jobs] == ["render"]
            assert reloaded_job is not None
            assert reloaded_job.status == "completed"
            assert reloaded_job.progress == 100
            assert reloaded_job.payload == {"source": "asset-1"}
            assert reloaded_job.result == {"output": "asset-2"}
            assert reloaded_job.started_at == started_at.replace(tzinfo=None)
            assert reloaded_job.finished_at == finished_at.replace(tzinfo=None)
            assert reloaded_job.attempts == 1

        await engine.dispose()

    asyncio.run(scenario())

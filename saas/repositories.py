from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from saas.models import Asset, Job, Project, User, Workspace


class WorkspaceRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, *, slug: str, name: str, plan: str = "free") -> Workspace:
        workspace = Workspace(slug=slug, name=name, plan=plan)
        self.session.add(workspace)
        await self.session.flush()
        return workspace

    async def get(self, workspace_id: UUID) -> Workspace | None:
        return await self.session.get(Workspace, workspace_id)

    async def get_by_slug(self, slug: str) -> Workspace | None:
        return await self.session.scalar(select(Workspace).where(Workspace.slug == slug))

    async def slug_exists(self, slug: str) -> bool:
        return await self.get_by_slug(slug) is not None


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        email: str,
        password_hash: str,
        full_name: str | None = None,
        role: str = "owner",
    ) -> User:
        user = User(
            workspace_id=workspace_id,
            email=email,
            full_name=full_name,
            role=role,
            password_hash=password_hash,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def get(self, user_id: UUID) -> User | None:
        return await self.session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(select(User).where(User.email == email))

    async def list_for_workspace(self, workspace_id: UUID) -> Sequence[User]:
        result = await self.session.scalars(
            select(User).where(User.workspace_id == workspace_id).order_by(User.created_at.asc())
        )
        return result.all()


class ProjectRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        kind: str,
        title: str | None = None,
        status: str = "draft",
    ) -> Project:
        project = Project(workspace_id=workspace_id, kind=kind, title=title, status=status)
        self.session.add(project)
        await self.session.flush()
        return project

    async def get(self, project_id: UUID) -> Project | None:
        return await self.session.get(Project, project_id)

    async def list_for_workspace(self, workspace_id: UUID) -> Sequence[Project]:
        result = await self.session.scalars(self._workspace_query(workspace_id))
        return result.all()

    async def set_status(self, project: Project, *, status: str) -> Project:
        project.status = status
        await self.session.flush()
        return project

    def _workspace_query(self, workspace_id: UUID) -> Select[tuple[Project]]:
        return (
            select(Project)
            .where(Project.workspace_id == workspace_id)
            .order_by(Project.created_at.desc(), Project.id.desc())
        )


class JobRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        workspace_id: UUID,
        kind: str,
        payload: dict[str, Any],
        project_id: UUID | None = None,
        status: str = "queued",
    ) -> Job:
        job = Job(
            workspace_id=workspace_id,
            project_id=project_id,
            kind=kind,
            status=status,
            payload=dict(payload),
        )
        self.session.add(job)
        await self.session.flush()
        return job

    async def get(self, job_id: UUID) -> Job | None:
        return await self.session.get(Job, job_id)

    async def list_for_workspace(self, workspace_id: UUID) -> Sequence[Job]:
        result = await self.session.scalars(self._workspace_query(workspace_id))
        return result.all()

    async def list_for_project(self, workspace_id: UUID, project_id: UUID) -> Sequence[Job]:
        result = await self.session.scalars(
            select(Job)
            .where(Job.workspace_id == workspace_id, Job.project_id == project_id)
            .order_by(Job.created_at.desc(), Job.id.desc())
        )
        return result.all()

    async def update_status(
        self,
        job: Job,
        *,
        status: str,
        progress: int | None = None,
        result_payload: dict[str, Any] | None = None,
        error_text: str | None = None,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        attempts: int | None = None,
    ) -> Job:
        job.status = status
        if progress is not None:
            job.progress = progress
        if result_payload is not None:
            job.result = dict(result_payload)
        if error_text is not None:
            job.error_text = error_text
        if started_at is not None:
            job.started_at = started_at
        if finished_at is not None:
            job.finished_at = finished_at
        if attempts is not None:
            job.attempts = attempts
        await self.session.flush()
        return job

    def _workspace_query(self, workspace_id: UUID) -> Select[tuple[Job]]:
        return select(Job).where(Job.workspace_id == workspace_id).order_by(Job.created_at.desc(), Job.id.desc())


class AssetRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        *,
        asset_id: UUID | None = None,
        workspace_id: UUID,
        storage_key: str,
        mime_type: str,
        size_bytes: int,
        kind: str,
        project_id: UUID | None = None,
    ) -> Asset:
        asset = Asset(
            id=asset_id,
            workspace_id=workspace_id,
            project_id=project_id,
            storage_key=storage_key,
            mime_type=mime_type,
            size_bytes=size_bytes,
            kind=kind,
        )
        self.session.add(asset)
        await self.session.flush()
        return asset

    async def get(self, asset_id: UUID) -> Asset | None:
        return await self.session.get(Asset, asset_id)


__all__ = [
    "AssetRepository",
    "JobRepository",
    "ProjectRepository",
    "UserRepository",
    "WorkspaceRepository",
]

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import create_access_token, hash_password, verify_password
from saas.models import Job, Project, User, Workspace
from saas.repositories import JobRepository, ProjectRepository, UserRepository, WorkspaceRepository


@dataclass
class AuthResult:
    access_token: str
    user: User
    workspace: Workspace


@dataclass
class ProjectJobResult:
    project: Project
    job: Job


@dataclass
class ProjectDetailResult:
    project: Project
    jobs: list[Job]


class AuthServiceError(Exception):
    """Base exception for SaaS authentication services."""


class UserAlreadyExistsError(AuthServiceError):
    pass


class InvalidCredentialsError(AuthServiceError):
    pass


class WorkflowServiceError(Exception):
    """Base exception for backend-only project and job workflows."""


class ProjectNotFoundError(WorkflowServiceError):
    pass


class JobNotFoundError(WorkflowServiceError):
    pass


class ProjectStateConflictError(WorkflowServiceError):
    pass


class JobStateConflictError(WorkflowServiceError):
    pass


class InvalidJobProgressError(WorkflowServiceError):
    pass


class AuthService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        token_issuer: Callable[[str | uuid.UUID, str | uuid.UUID], str] = create_access_token,
    ):
        self.session = session
        self.workspaces = WorkspaceRepository(session)
        self.users = UserRepository(session)
        self._token_issuer = token_issuer

    async def signup_owner(
        self,
        *,
        workspace_name: str,
        full_name: str,
        email: str,
        password: str,
    ) -> AuthResult:
        normalized_name = workspace_name.strip()
        normalized_full_name = full_name.strip()
        normalized_email = email.strip().lower()

        if await self.users.get_by_email(normalized_email) is not None:
            raise UserAlreadyExistsError(normalized_email)

        try:
            workspace = await self.workspaces.create(
                slug=await self._unique_workspace_slug(normalized_name),
                name=normalized_name,
                plan="free",
            )
            user = await self.users.create(
                workspace_id=workspace.id,
                email=normalized_email,
                full_name=normalized_full_name,
                role="owner",
                password_hash=hash_password(password),
            )
            access_token = self._token_issuer(user.id, workspace.id)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return AuthResult(access_token=access_token, user=user, workspace=workspace)

    async def authenticate(self, *, email: str, password: str) -> AuthResult:
        normalized_email = email.strip().lower()
        user = await self.users.get_by_email(normalized_email)
        if user is None or not verify_password(password, user.password_hash):
            raise InvalidCredentialsError(normalized_email)

        workspace = await self.workspaces.get(user.workspace_id)
        if workspace is None:
            raise InvalidCredentialsError(normalized_email)

        return AuthResult(
            access_token=self._token_issuer(user.id, workspace.id),
            user=user,
            workspace=workspace,
        )

    async def _unique_workspace_slug(self, workspace_name: str) -> str:
        base_slug = slugify_workspace_name(workspace_name)
        candidate = base_slug
        suffix = 2

        while True:
            if not await self.workspaces.slug_exists(candidate):
                return candidate
            candidate = f"{base_slug}-{suffix}"
            suffix += 1


class WorkflowService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.projects = ProjectRepository(session)
        self.jobs = JobRepository(session)

    async def create_project(
        self,
        *,
        workspace_id: uuid.UUID,
        kind: str,
        title: str | None = None,
    ) -> Project:
        try:
            project = await self.projects.create(
                workspace_id=workspace_id,
                kind=_normalize_required_text(kind, field_name="kind"),
                title=_normalize_optional_text(title),
                status="draft",
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return project

    async def list_projects(self, *, workspace_id: uuid.UUID) -> list[Project]:
        projects = await self.projects.list_for_workspace(workspace_id)
        return list(projects)

    async def list_jobs(self, *, workspace_id: uuid.UUID) -> list[Job]:
        jobs = await self.jobs.list_for_workspace(workspace_id)
        return list(jobs)

    async def get_project_detail(self, *, workspace_id: uuid.UUID, project_id: uuid.UUID) -> ProjectDetailResult:
        project = await self._get_project(workspace_id=workspace_id, project_id=project_id)
        jobs = await self.jobs.list_for_project(workspace_id, project.id)
        return ProjectDetailResult(project=project, jobs=list(jobs))

    async def create_project_job(
        self,
        *,
        workspace_id: uuid.UUID,
        project_kind: str,
        job_kind: str,
        payload: dict[str, Any],
        title: str | None = None,
    ) -> ProjectJobResult:
        try:
            project = await self.projects.create(
                workspace_id=workspace_id,
                kind=_normalize_required_text(project_kind, field_name="project_kind"),
                title=_normalize_optional_text(title),
                status="queued",
            )
            job = await self.jobs.create(
                workspace_id=workspace_id,
                project_id=project.id,
                kind=_normalize_required_text(job_kind, field_name="job_kind"),
                payload=_copy_payload(payload),
                status="queued",
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return ProjectJobResult(project=project, job=job)

    async def queue_job(
        self,
        *,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
        kind: str,
        payload: dict[str, Any],
    ) -> Job:
        try:
            project = await self._get_project(workspace_id=workspace_id, project_id=project_id)
            if project.status in TERMINAL_PROJECT_STATUSES:
                raise ProjectStateConflictError(project.status)

            job = await self.jobs.create(
                workspace_id=workspace_id,
                project_id=project.id,
                kind=_normalize_required_text(kind, field_name="kind"),
                payload=_copy_payload(payload),
                status="queued",
            )
            await self.projects.set_status(project, status="queued")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return job

    async def start_job(
        self,
        *,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        started_at: datetime | None = None,
    ) -> Job:
        try:
            job = await self._get_job(workspace_id=workspace_id, job_id=job_id)
            if job.status != "queued":
                raise JobStateConflictError(job.status)

            started_at_value = _normalize_timestamp(started_at)
            await self.jobs.update_status(
                job,
                status="processing",
                progress=max(job.progress, 0),
                started_at=started_at_value,
                attempts=job.attempts + 1,
            )
            await self._set_project_status_for_job(job, status="processing")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return job

    async def update_job_progress(
        self,
        *,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        progress: int,
    ) -> Job:
        validated_progress = _validate_progress(progress)

        try:
            job = await self._get_job(workspace_id=workspace_id, job_id=job_id)
            if job.status != "processing":
                raise JobStateConflictError(job.status)

            await self.jobs.update_status(job, status="processing", progress=validated_progress)
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return job

    async def complete_job(
        self,
        *,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        result_payload: dict[str, Any],
        finished_at: datetime | None = None,
    ) -> Job:
        try:
            job = await self._get_job(workspace_id=workspace_id, job_id=job_id)
            if job.status != "processing":
                raise JobStateConflictError(job.status)

            await self.jobs.update_status(
                job,
                status="completed",
                progress=100,
                result_payload=_copy_payload(result_payload),
                finished_at=_normalize_timestamp(finished_at),
            )
            await self._set_project_status_for_job(job, status="completed")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return job

    async def fail_job(
        self,
        *,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        error_text: str,
        finished_at: datetime | None = None,
    ) -> Job:
        try:
            job = await self._get_job(workspace_id=workspace_id, job_id=job_id)
            if job.status not in ACTIVE_JOB_STATUSES:
                raise JobStateConflictError(job.status)

            await self.jobs.update_status(
                job,
                status="failed",
                error_text=_normalize_required_text(error_text, field_name="error_text"),
                finished_at=_normalize_timestamp(finished_at),
            )
            await self._set_project_status_for_job(job, status="failed")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return job

    async def retry_job(
        self,
        *,
        workspace_id: uuid.UUID,
        job_id: uuid.UUID,
        legacy_job_id: str | None = None,
        source_asset_id: uuid.UUID | None = None,
    ) -> Job:
        try:
            job = await self._get_job(workspace_id=workspace_id, job_id=job_id)
            if job.status != "failed":
                raise JobStateConflictError(job.status)
            if job.project_id is None:
                raise ValueError("Only project-backed jobs can be retried")

            payload = _copy_payload(job.payload)
            if legacy_job_id is not None:
                payload["legacy_job_id"] = legacy_job_id.strip()
            if source_asset_id is not None:
                payload["source_asset_id"] = str(source_asset_id)
            payload["retry_of_job_id"] = str(job.id)

            retried_job = await self.jobs.create(
                workspace_id=workspace_id,
                project_id=job.project_id,
                kind=job.kind,
                payload=payload,
                status="queued",
            )
            project = await self._get_project(workspace_id=workspace_id, project_id=job.project_id)
            await self.projects.set_status(project, status="queued")
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

        return retried_job

    async def _get_project(self, *, workspace_id: uuid.UUID, project_id: uuid.UUID) -> Project:
        project = await self.projects.get(project_id)
        if project is None or project.workspace_id != workspace_id:
            raise ProjectNotFoundError(str(project_id))
        return project

    async def _get_job(self, *, workspace_id: uuid.UUID, job_id: uuid.UUID) -> Job:
        job = await self.jobs.get(job_id)
        if job is None or job.workspace_id != workspace_id:
            raise JobNotFoundError(str(job_id))
        return job

    async def _set_project_status_for_job(self, job: Job, *, status: str) -> None:
        if job.project_id is None:
            return

        project = await self._get_project(workspace_id=job.workspace_id, project_id=job.project_id)
        await self.projects.set_status(project, status=status)


ACTIVE_JOB_STATUSES = {"queued", "processing"}
TERMINAL_PROJECT_STATUSES = {"completed", "failed"}


def _copy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_required_text(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_timestamp(value: datetime | None) -> datetime:
    timestamp = value or datetime.now(timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _validate_progress(progress: int) -> int:
    if not 0 <= progress <= 100:
        raise InvalidJobProgressError(progress)
    return progress


def slugify_workspace_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "workspace"


__all__ = [
    "AuthResult",
    "AuthService",
    "AuthServiceError",
    "InvalidJobProgressError",
    "InvalidCredentialsError",
    "JobNotFoundError",
    "JobStateConflictError",
    "ProjectJobResult",
    "ProjectNotFoundError",
    "ProjectStateConflictError",
    "UserAlreadyExistsError",
    "WorkflowService",
    "WorkflowServiceError",
    "slugify_workspace_name",
]

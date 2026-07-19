from __future__ import annotations

import uuid

import os

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import CurrentSession, get_current_session
from saas.database import get_db
from saas.repositories import AssetRepository
from saas.schemas import (
    JobCompleteRequest,
    JobCreateRequest,
    ProjectDetailResponse,
    JobListResponse,
    JobFailRequest,
    JobProgressRequest,
    JobRetryRequest,
    JobResponse,
    JobStartRequest,
    ProjectCreateRequest,
    ProjectListResponse,
    ProjectJobCreateRequest,
    ProjectJobResponse,
    ProjectResponse,
)
from saas.services import (
    InvalidJobProgressError,
    JobNotFoundError,
    JobStateConflictError,
    ProjectNotFoundError,
    ProjectStateConflictError,
    WorkflowService,
)
from saas.storage import resolve_source_asset_path

router = APIRouter(tags=["saas-workflow"])


def _workflow_http_exception(exc: Exception) -> HTTPException:
    if isinstance(exc, ProjectNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if isinstance(exc, JobNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if isinstance(exc, ProjectStateConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project state conflict: {exc.args[0]}",
        )
    if isinstance(exc, JobStateConflictError):
        return HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Job state conflict: {exc.args[0]}",
        )
    if isinstance(exc, InvalidJobProgressError):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Progress must be between 0 and 100",
        )
    if isinstance(exc, ValueError):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    raise exc


@router.get("/api/saas/projects", response_model=ProjectListResponse)
async def list_projects(
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> ProjectListResponse:
    service = WorkflowService(db)
    projects = await service.list_projects(workspace_id=current.workspace.id)
    return ProjectListResponse(projects=[ProjectResponse.model_validate(project) for project in projects])


@router.get("/api/saas/projects/{project_id}", response_model=ProjectDetailResponse)
async def get_project_detail(
    project_id: uuid.UUID,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> ProjectDetailResponse:
    service = WorkflowService(db)
    try:
        detail = await service.get_project_detail(workspace_id=current.workspace.id, project_id=project_id)
    except ProjectNotFoundError as exc:
        raise _workflow_http_exception(exc) from exc

    return ProjectDetailResponse(
        project=ProjectResponse.model_validate(detail.project),
        jobs=[JobResponse.model_validate(job) for job in detail.jobs],
    )


@router.get("/api/saas/jobs", response_model=JobListResponse)
async def list_jobs(
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> JobListResponse:
    service = WorkflowService(db)
    jobs = await service.list_jobs(workspace_id=current.workspace.id)
    return JobListResponse(jobs=[JobResponse.model_validate(job) for job in jobs])


@router.post("/api/saas/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> ProjectResponse:
    service = WorkflowService(db)

    try:
        project = await service.create_project(
            workspace_id=current.workspace.id,
            kind=payload.kind,
            title=payload.title,
        )
    except (ProjectStateConflictError, ValueError) as exc:
        raise _workflow_http_exception(exc) from exc

    return ProjectResponse.model_validate(project)


@router.post("/api/saas/projects/with-job", response_model=ProjectJobResponse, status_code=status.HTTP_201_CREATED)
async def create_project_with_job(
    payload: ProjectJobCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> ProjectJobResponse:
    service = WorkflowService(db)

    try:
        result = await service.create_project_job(
            workspace_id=current.workspace.id,
            project_kind=payload.project_kind,
            job_kind=payload.job_kind,
            payload=payload.payload,
            title=payload.title,
        )
    except ValueError as exc:
        raise _workflow_http_exception(exc) from exc

    return ProjectJobResponse(
        project=ProjectResponse.model_validate(result.project),
        job=JobResponse.model_validate(result.job),
    )


@router.post(
    "/api/saas/projects/{project_id}/jobs",
    response_model=JobResponse,
    status_code=status.HTTP_201_CREATED,
)
async def queue_job(
    project_id: uuid.UUID,
    payload: JobCreateRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    service = WorkflowService(db)

    try:
        job = await service.queue_job(
            workspace_id=current.workspace.id,
            project_id=project_id,
            kind=payload.kind,
            payload=payload.payload,
        )
    except (ProjectNotFoundError, ProjectStateConflictError, ValueError) as exc:
        raise _workflow_http_exception(exc) from exc

    return JobResponse.model_validate(job)


@router.post("/api/saas/jobs/{job_id}/start", response_model=JobResponse)
async def start_job(
    job_id: uuid.UUID,
    payload: JobStartRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    service = WorkflowService(db)

    try:
        job = await service.start_job(
            workspace_id=current.workspace.id,
            job_id=job_id,
            started_at=payload.started_at,
        )
    except (JobNotFoundError, JobStateConflictError) as exc:
        raise _workflow_http_exception(exc) from exc

    return JobResponse.model_validate(job)


@router.post("/api/saas/jobs/{job_id}/progress", response_model=JobResponse)
async def update_job_progress(
    job_id: uuid.UUID,
    payload: JobProgressRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    service = WorkflowService(db)

    try:
        job = await service.update_job_progress(
            workspace_id=current.workspace.id,
            job_id=job_id,
            progress=payload.progress,
        )
    except (JobNotFoundError, JobStateConflictError, InvalidJobProgressError) as exc:
        raise _workflow_http_exception(exc) from exc

    return JobResponse.model_validate(job)


@router.post("/api/saas/jobs/{job_id}/complete", response_model=JobResponse)
async def complete_job(
    job_id: uuid.UUID,
    payload: JobCompleteRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    service = WorkflowService(db)

    try:
        job = await service.complete_job(
            workspace_id=current.workspace.id,
            job_id=job_id,
            result_payload=payload.result_payload,
            finished_at=payload.finished_at,
        )
    except JobNotFoundError as exc:
        raise _workflow_http_exception(exc) from exc
    except JobStateConflictError as exc:
        raise _workflow_http_exception(exc) from exc

    return JobResponse.model_validate(job)


@router.post("/api/saas/jobs/{job_id}/fail", response_model=JobResponse)
async def fail_job(
    job_id: uuid.UUID,
    payload: JobFailRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    service = WorkflowService(db)

    try:
        job = await service.fail_job(
            workspace_id=current.workspace.id,
            job_id=job_id,
            error_text=payload.error_text,
            finished_at=payload.finished_at,
        )
    except (JobNotFoundError, JobStateConflictError, ValueError) as exc:
        raise _workflow_http_exception(exc) from exc

    return JobResponse.model_validate(job)


@router.post("/api/saas/jobs/{job_id}/retry", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
async def retry_job(
    job_id: uuid.UUID,
    payload: JobRetryRequest,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
) -> JobResponse:
    service = WorkflowService(db)

    try:
        job = await service.retry_job(
            workspace_id=current.workspace.id,
            job_id=job_id,
            legacy_job_id=payload.legacy_job_id,
            source_asset_id=payload.source_asset_id,
        )
    except (JobNotFoundError, JobStateConflictError, ValueError) as exc:
        raise _workflow_http_exception(exc) from exc

    return JobResponse.model_validate(job)


@router.get("/api/saas/assets/{asset_id}/content")
async def get_asset_content(
    asset_id: uuid.UUID,
    current: CurrentSession = Depends(get_current_session),
    db: AsyncSession = Depends(get_db),
):
    assets = AssetRepository(db)
    asset = await assets.get(asset_id)
    if asset is None or asset.workspace_id != current.workspace.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found")

    try:
        file_path = resolve_source_asset_path(asset.storage_key)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset not found") from exc

    if not os.path.exists(file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Asset file not found")

    return FileResponse(file_path, media_type=asset.mime_type, filename=os.path.basename(file_path))

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class SignupRequest(BaseModel):
    workspace_name: str = Field(min_length=2, max_length=160)
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    password: str = Field(min_length=8)


class AuthUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    full_name: str | None = None
    role: str


class AuthWorkspace(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    plan: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: AuthUser
    workspace: AuthWorkspace


class SessionResponse(BaseModel):
    user: AuthUser
    workspace: AuthWorkspace


class ProjectCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=40)
    title: str | None = Field(default=None, max_length=255)


class ProjectJobCreateRequest(BaseModel):
    project_kind: str = Field(min_length=1, max_length=40)
    job_kind: str = Field(min_length=1, max_length=60)
    payload: dict[str, Any] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=255)


class JobCreateRequest(BaseModel):
    kind: str = Field(min_length=1, max_length=60)
    payload: dict[str, Any] = Field(default_factory=dict)


class JobStartRequest(BaseModel):
    started_at: datetime | None = None


class JobProgressRequest(BaseModel):
    progress: int = Field(ge=0, le=100)


class JobCompleteRequest(BaseModel):
    result_payload: dict[str, Any] = Field(default_factory=dict)
    finished_at: datetime | None = None


class JobFailRequest(BaseModel):
    error_text: str = Field(min_length=1)
    finished_at: datetime | None = None


class JobRetryRequest(BaseModel):
    legacy_job_id: str | None = Field(default=None, min_length=1)
    source_asset_id: uuid.UUID | None = None


class ProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    kind: str
    title: str | None = None
    status: str
    created_at: datetime


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]


class JobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    project_id: uuid.UUID | None = None
    kind: str
    status: str
    payload: dict[str, Any]
    result: dict[str, Any] | None = None
    error_text: str | None = None
    progress: int
    attempts: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobListResponse(BaseModel):
    jobs: list[JobResponse]


class ProjectDetailResponse(BaseModel):
    project: ProjectResponse
    jobs: list[JobResponse]


class ProjectJobResponse(BaseModel):
    project: ProjectResponse
    job: JobResponse

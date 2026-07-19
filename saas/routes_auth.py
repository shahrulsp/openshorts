from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from saas.auth import CurrentSession, get_current_session
from saas.database import get_db
from saas.schemas import AuthTokenResponse, LoginRequest, SessionResponse, SignupRequest
from saas.services import AuthService, InvalidCredentialsError, UserAlreadyExistsError

router = APIRouter(tags=["saas-auth"])


@router.post("/api/saas/auth/signup", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)) -> AuthTokenResponse:
    service = AuthService(db)

    try:
        result = await service.signup_owner(
            workspace_name=payload.workspace_name,
            full_name=payload.full_name,
            email=str(payload.email),
            password=payload.password,
        )
    except UserAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User already exists") from exc

    return AuthTokenResponse(access_token=result.access_token, user=result.user, workspace=result.workspace)


@router.post("/api/saas/auth/login", response_model=AuthTokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> AuthTokenResponse:
    service = AuthService(db)

    try:
        result = await service.authenticate(email=str(payload.email), password=payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password") from exc

    return AuthTokenResponse(access_token=result.access_token, user=result.user, workspace=result.workspace)


@router.get("/api/saas/me", response_model=SessionResponse)
async def get_me(current: CurrentSession = Depends(get_current_session)) -> SessionResponse:
    return SessionResponse(user=current.user, workspace=current.workspace)

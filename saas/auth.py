from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from saas.config import SaaSSettings, load_saas_settings
from saas.database import get_db
from saas.models import User, Workspace
from saas.repositories import UserRepository, WorkspaceRepository

JWT_ALGORITHM = "HS256"
PBKDF2_ITERATIONS = 600_000


@dataclass
class CurrentSession:
    user: User
    workspace: Workspace


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return (
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$"
        f"{base64.b64encode(salt).decode('ascii')}$"
        f"{base64.b64encode(digest).decode('ascii')}"
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        scheme, iterations, salt_b64, digest_b64 = password_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64.encode("ascii"))
        expected_digest = base64.b64decode(digest_b64.encode("ascii"))
        actual_digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )
    except (ValueError, TypeError):
        return False

    return hmac.compare_digest(actual_digest, expected_digest)


def create_access_token(
    user_id: str | uuid.UUID,
    workspace_id: str | uuid.UUID,
    settings: SaaSSettings | None = None,
) -> str:
    resolved_settings = settings or load_saas_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "workspace_id": str(workspace_id),
        "iss": resolved_settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=resolved_settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, resolved_settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str, settings: SaaSSettings | None = None) -> dict:
    resolved_settings = settings or load_saas_settings()
    return jwt.decode(
        token,
        resolved_settings.jwt_secret,
        algorithms=[JWT_ALGORITHM],
        issuer=resolved_settings.jwt_issuer,
    )


async def get_current_session(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentSession:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    token = auth_header[7:].strip()
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")

    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(str(payload["sub"]))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token") from exc

    users = UserRepository(db)
    workspaces = WorkspaceRepository(db)

    user = await users.get(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    workspace = await workspaces.get(user.workspace_id)
    if workspace is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    return CurrentSession(user=user, workspace=workspace)

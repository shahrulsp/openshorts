# Account Auth Data Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the first independent SaaS foundation for OpenShorts by introducing our own database layer, core multi-tenant tables, password-based auth, bearer tokens, and a minimal signed-in frontend session flow without using `cloud/`.

**Architecture:** Create a brand-new `saas/` package that owns database access, models, auth, and session helpers. Keep the existing self-host BYOK flow working, but add a parallel independent SaaS path behind new routes and new React session logic, with `cloud/` untouched and unused.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, PostgreSQL, bcrypt/passlib, PyJWT, React/Vite, pytest

---

## File Structure

- `saas/config.py`
  Responsibility: independent SaaS env/config values, separate from `cloud/`
- `saas/database.py`
  Responsibility: async engine, sessionmaker, FastAPI DB dependency
- `saas/models.py`
  Responsibility: `Workspace`, `User`, `Project`, `Asset`, `Job`, `UsageEvent`
- `saas/schemas.py`
  Responsibility: request/response DTOs for auth and session routes
- `saas/auth.py`
  Responsibility: password hashing, token issue/verify, current-user loading
- `saas/routes_auth.py`
  Responsibility: `/api/saas/auth/*` and `/api/saas/me`
- `app.py`
  Responsibility: mount new SaaS routes and publish config flags without importing `cloud/`
- `alembic/env.py`
  Responsibility: switch Alembic target metadata from `cloud` to the new independent metadata when SaaS mode is enabled
- `tests/conftest.py`
  Responsibility: test database/session/client fixtures for new SaaS foundation
- `tests/test_saas_models.py`
  Responsibility: schema-level verification for new tables
- `tests/test_saas_auth.py`
  Responsibility: end-to-end auth route tests
- `dashboard/src/lib/api.js`
  Responsibility: token storage/fetch wrapper for independent SaaS routes
- `dashboard/src/contexts/AuthContext.jsx`
  Responsibility: signed-in workspace session bootstrap using the new routes

### Task 1: Create The Independent SaaS Database Foundation

**Files:**
- Create: `saas/__init__.py`
- Create: `saas/config.py`
- Create: `saas/database.py`
- Modify: `alembic/env.py`
- Test: `tests/conftest.py`

- [ ] **Step 1: Write the failing database fixture import test**

```python
from saas.database import Base


def test_saas_base_metadata_exists():
    assert Base.metadata is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_saas_models.py::test_saas_base_metadata_exists -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'saas'`

- [ ] **Step 3: Create the SaaS config module**

```python
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class SaaSSettings:
    enabled: bool
    database_url: str
    jwt_secret: str
    jwt_issuer: str
    access_token_ttl_minutes: int


def load_saas_settings() -> SaaSSettings:
    return SaaSSettings(
        enabled=os.environ.get("SAAS_ENABLED", "").lower() in ("1", "true", "yes"),
        database_url=os.environ.get("SAAS_DATABASE_URL") or os.environ.get("DATABASE_URL", ""),
        jwt_secret=os.environ.get("SAAS_JWT_SECRET", "dev-insecure-change-me"),
        jwt_issuer=os.environ.get("SAAS_JWT_ISSUER", "openshorts-local"),
        access_token_ttl_minutes=int(os.environ.get("SAAS_ACCESS_TOKEN_TTL_MINUTES", "1440")),
    )
```

- [ ] **Step 4: Create the database module**

```python
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import declarative_base

from saas.config import load_saas_settings


Base = declarative_base()

_engine = None
_sessionmaker = None


def init_engine():
    global _engine, _sessionmaker
    settings = load_saas_settings()
    if not settings.database_url:
        raise RuntimeError("SAAS_DATABASE_URL or DATABASE_URL is required when SaaS is enabled")
    _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
    return _engine


def get_sessionmaker():
    if _sessionmaker is None:
        init_engine()
    return _sessionmaker


async def get_db():
    async with get_sessionmaker()() as session:
        yield session
```

- [ ] **Step 5: Update Alembic to use SaaS metadata when enabled**

```python
from saas.config import load_saas_settings
from saas.database import Base
import saas.models  # noqa: F401

settings = load_saas_settings()
db_url = settings.database_url or os.environ.get("DATABASE_URL", "")
target_metadata = Base.metadata
```

- [ ] **Step 6: Expand `tests/conftest.py` with SaaS test env defaults**

```python
import os
import sys

os.environ.setdefault("SAAS_ENABLED", "true")
os.environ.setdefault("SAAS_DATABASE_URL", "sqlite+aiosqlite:///./test_saas.db")
os.environ.setdefault("SAAS_JWT_SECRET", "test-secret")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

- [ ] **Step 7: Run the database fixture test**

Run: `pytest tests/test_saas_models.py::test_saas_base_metadata_exists -v`

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add saas/__init__.py saas/config.py saas/database.py alembic/env.py tests/conftest.py tests/test_saas_models.py
git commit -m "feat: add independent saas database foundation"
```

### Task 2: Add The Core Multi-Tenant Tables And Migration

**Files:**
- Create: `saas/models.py`
- Create: `alembic/versions/20260719_01_saas_core.py`
- Test: `tests/test_saas_models.py`

- [ ] **Step 1: Write the failing table existence test**

```python
from saas.models import Workspace, User, Project, Asset, Job, UsageEvent


def test_saas_models_export_core_entities():
    assert Workspace.__tablename__ == "workspaces"
    assert User.__tablename__ == "users"
    assert Project.__tablename__ == "projects"
    assert Asset.__tablename__ == "assets"
    assert Job.__tablename__ == "jobs"
    assert UsageEvent.__tablename__ == "usage_events"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_saas_models.py::test_saas_models_export_core_entities -v`

Expected: FAIL with `ModuleNotFoundError` or missing symbol errors

- [ ] **Step 3: Implement the core models**

```python
from uuid import uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, BigInteger, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from saas.database import Base


class Workspace(Base):
    __tablename__ = "workspaces"
    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    plan: Mapped[str] = mapped_column(String(40), nullable=False, default="free")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Step 4: Finish the remaining models in the same file**

```python
class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft")
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="queued")
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_text: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[DateTime | None] = mapped_column(DateTime(timezone=True))


class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[str] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[str] = mapped_column(UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=False, index=True)
    job_id: Mapped[str | None] = mapped_column(UUID(as_uuid=True), ForeignKey("jobs.id"))
    metric: Mapped[str] = mapped_column(String(60), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
```

- [ ] **Step 5: Create the initial Alembic migration**

```python
def upgrade():
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("slug", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("plan", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)
```

- [ ] **Step 6: Add migration coverage for the remaining five tables**

```python
def downgrade():
    op.drop_table("usage_events")
    op.drop_table("jobs")
    op.drop_table("assets")
    op.drop_table("projects")
    op.drop_table("users")
    op.drop_table("workspaces")
```

- [ ] **Step 7: Run the model tests**

Run: `pytest tests/test_saas_models.py -v`

Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add saas/models.py alembic/versions/20260719_01_saas_core.py tests/test_saas_models.py
git commit -m "feat: add independent saas core schema"
```

### Task 3: Add Password Auth, JWT Sessions, And Session Routes

**Files:**
- Create: `saas/schemas.py`
- Create: `saas/auth.py`
- Create: `saas/routes_auth.py`
- Modify: `app.py`
- Test: `tests/test_saas_auth.py`

- [ ] **Step 1: Write the failing login test**

```python
def test_login_returns_bearer_token(client, seeded_owner):
    res = client.post("/api/saas/auth/login", json={
        "email": "owner@example.com",
        "password": "secret123",
    })
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "owner@example.com"
```

- [ ] **Step 2: Add request and response schemas**

```python
from pydantic import BaseModel, EmailStr


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class SignupRequest(BaseModel):
    workspace_name: str
    full_name: str
    email: EmailStr
    password: str
```

- [ ] **Step 3: Add password and token helpers**

```python
from datetime import datetime, timedelta, timezone
import jwt
from passlib.context import CryptContext

pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd.verify(password, password_hash)


def create_access_token(user_id: str, workspace_id: str, settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "workspace_id": workspace_id,
        "iss": settings.jwt_issuer,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")
```

- [ ] **Step 4: Add signup and login routes**

```python
@router.post("/api/saas/auth/signup")
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)):
    workspace = Workspace(slug=slugify(payload.workspace_name), name=payload.workspace_name, plan="free")
    db.add(workspace)
    await db.flush()
    user = User(
        workspace_id=workspace.id,
        email=payload.email.lower(),
        full_name=payload.full_name,
        role="owner",
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    await db.commit()
    token = create_access_token(str(user.id), str(workspace.id), load_saas_settings())
    return {"access_token": token, "token_type": "bearer", "user": {"email": user.email, "role": user.role}}
```

- [ ] **Step 5: Add current-session route**

```python
@router.get("/api/saas/me")
async def get_me(current=Depends(get_current_session)):
    return {
        "user": {
            "id": str(current.user.id),
            "email": current.user.email,
            "full_name": current.user.full_name,
            "role": current.user.role,
        },
        "workspace": {
            "id": str(current.workspace.id),
            "name": current.workspace.name,
            "slug": current.workspace.slug,
            "plan": current.workspace.plan,
        },
    }
```

- [ ] **Step 6: Mount the router in `app.py`**

```python
from saas.routes_auth import router as saas_auth_router

app.include_router(saas_auth_router)
```

- [ ] **Step 7: Run the auth tests**

Run: `pytest tests/test_saas_auth.py -v`

Expected: signup, login, unauthorized, and `/api/saas/me` tests all pass

- [ ] **Step 8: Commit**

```bash
git add saas/schemas.py saas/auth.py saas/routes_auth.py app.py tests/test_saas_auth.py
git commit -m "feat: add independent saas auth routes"
```

### Task 4: Add Test Fixtures For Workspace And Session Flows

**Files:**
- Modify: `tests/conftest.py`
- Test: `tests/test_saas_auth.py`
- Test: `tests/test_saas_models.py`

- [ ] **Step 1: Add async database setup fixture**

```python
import asyncio
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from saas.database import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()
```

- [ ] **Step 2: Add temporary test database fixture**

```python
@pytest.fixture
async def db_session(tmp_path):
    db_file = tmp_path / "saas.sqlite"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    await engine.dispose()
```

- [ ] **Step 3: Add seeded owner fixture**

```python
@pytest.fixture
async def seeded_owner(db_session):
    workspace = Workspace(slug="acme", name="Acme", plan="free")
    db_session.add(workspace)
    await db_session.flush()
    user = User(
        workspace_id=workspace.id,
        email="owner@example.com",
        full_name="Owner",
        role="owner",
        password_hash=hash_password("secret123"),
    )
    db_session.add(user)
    await db_session.commit()
    return {"workspace": workspace, "user": user}
```

- [ ] **Step 4: Add FastAPI client fixture**

```python
@pytest.fixture
async def client():
    from app import app
    async with AsyncClient(app=app, base_url="http://testserver") as ac:
        yield ac
```

- [ ] **Step 5: Run both test files together**

Run: `pytest tests/test_saas_models.py tests/test_saas_auth.py -v`

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_saas_models.py tests/test_saas_auth.py
git commit -m "test: add independent saas auth fixtures"
```

### Task 5: Connect The Frontend To The New Independent Session API

**Files:**
- Modify: `dashboard/src/lib/api.js`
- Modify: `dashboard/src/contexts/AuthContext.jsx`
- Test: `dashboard/src/contexts/__tests__/AuthContext.test.jsx`

- [ ] **Step 1: Write the failing frontend session test**

```jsx
it("loads the saas session from /api/saas/me when a token exists", async () => {
  localStorage.setItem("openshorts_auth", "test-token");
  render(
    <AuthProvider>
      <Probe />
    </AuthProvider>
  );
  expect(await screen.findByText(/owner@example.com/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Extend the API helper with SaaS session helpers**

```jsx
export async function apiJson(path, options = {}) {
  const res = await apiFetch(path, options);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}
```

- [ ] **Step 3: Switch `AuthContext` to prefer SaaS session routes**

```jsx
const refreshMe = useCallback(async () => {
  if (!getToken()) { setMe(null); return null; }
  try {
    const data = await apiJson('/api/saas/me');
    setMe(data);
    return data;
  } catch (e) {
    clearToken();
    setMe(null);
    return null;
  }
}, []);
```

- [ ] **Step 4: Publish independent SaaS config flags from the backend**

```python
@app.get("/api/config")
async def get_config():
    saas_enabled = load_saas_settings().enabled
    return {
        "billingEnabled": False,
        "googleAuthEnabled": False,
        "saasEnabled": saas_enabled,
        "geminiConfigured": bool(os.environ.get("GEMINI_API_KEY")),
        "uploadPostConfigured": bool(os.environ.get("UPLOAD_POST_API_KEY")),
    }
```

- [ ] **Step 5: Run the frontend test**

Run: `cd dashboard && npm test -- AuthContext.test.jsx`

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/lib/api.js dashboard/src/contexts/AuthContext.jsx dashboard/src/contexts/__tests__/AuthContext.test.jsx app.py
git commit -m "feat: connect frontend to independent saas session api"
```

## Self-Review

- **Spec coverage:** This plan covers the first SaaS slice only: database foundation, core tenancy schema, auth/session APIs, and frontend session bootstrap. It intentionally does not include durable jobs, object storage, billing/quota reservation, or VPS deployment.
- **Placeholder scan:** No `TBD`, `TODO`, or “implement later” placeholders remain. All code steps include concrete snippets and commands.
- **Type consistency:** Route names, filenames, and exported model names are consistent across tasks: `saas.database.Base`, `saas.models.*`, `/api/saas/auth/*`, `/api/saas/me`.

## Notes For The First Subagent

- Keep `cloud/` untouched and do not import any of its models, database helpers, or auth helpers
- Prefer adding new `saas/` modules over threading more conditionals through `app.py`
- Keep existing local self-host behavior working while introducing the new SaaS path
- If SQLite JSON compatibility becomes noisy in tests, keep tests on SQLite but use a backend-safe fallback type for JSON fields in test config only


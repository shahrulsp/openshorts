# Independent SaaS Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Design and implement a fully independent SaaS architecture for OpenShorts without using any code from `cloud/`.

**Architecture:** Keep the existing FastAPI, React, and Remotion core, but replace all hosted concerns with our own account, billing, quota, storage, and job system. Treat the current repo as an open-core video pipeline and wrap it with new multi-tenant SaaS boundaries rather than extending `BILLING_ENABLED` or importing `cloud/`.

**Tech Stack:** FastAPI, PostgreSQL, Redis, React/Vite, Remotion, S3-compatible object storage, Stripe, background workers, Alembic, Docker Compose

---

## Scope Split

This effort spans multiple independent subsystems. Do **not** implement it as one giant branch. Split work into these sub-projects:

1. Account + Auth foundation
2. Projects + storage + job orchestration
3. Billing + quota + usage ledger
4. Frontend managed SaaS shell
5. VPS production deployment

This master plan defines the target architecture and execution order. Each subsystem should get its own follow-up implementation plan before coding starts.

### Task 1: Freeze The Target Architecture

**Files:**
- Create: `docs/architecture/independent-saas-overview.md`
- Create: `docs/architecture/service-boundaries.md`
- Create: `docs/architecture/domain-glossary.md`
- Reference: `app.py`
- Reference: `dashboard/src/App.jsx`
- Reference: `render-service/src/server.ts`

- [ ] **Step 1: Write the architecture overview document**

```md
# Independent SaaS Overview

## Principles
- Never import or depend on `cloud/`
- Keep the media pipeline working during migration
- Prefer composition over a flag-heavy monolith
- Persist tenant, job, and asset state in PostgreSQL + object storage
- Use Redis only for queueing, locks, and ephemeral coordination

## Services
- `api`: FastAPI app for auth, projects, jobs, uploads, settings, billing webhooks
- `worker-media`: executes clip generation, subtitles, hooks, translate, dubbing
- `worker-render`: existing Remotion renderer behind a durable job contract
- `frontend`: React dashboard for authenticated users
- `postgres`: source of truth for accounts, projects, jobs, quotas, plans, events
- `redis`: queue broker + distributed locks
- `object-storage`: S3-compatible bucket for uploads, outputs, previews, thumbnails
```

- [ ] **Step 2: Write the service boundary document**

```md
# Service Boundaries

## API service
- Accepts authenticated requests
- Creates upload intents
- Creates project/job records
- Publishes background work
- Returns signed URLs and durable job status

## Media worker
- Pulls queued jobs
- Downloads source inputs from object storage
- Runs existing Python pipeline modules
- Uploads outputs and structured metadata
- Writes progress/events back to PostgreSQL

## Render worker
- Receives render jobs via queue or internal API
- Reads source assets from object storage
- Writes rendered artifacts back to object storage
- Reports progress/events back to PostgreSQL
```

- [ ] **Step 3: Write the domain glossary**

```md
# Domain Glossary

- `workspace`: top-level tenant account
- `user`: authenticated member of a workspace
- `project`: durable container for one clip session, AI short, or thumbnail workflow
- `asset`: uploaded or generated media object with owner, bucket key, mime, size
- `job`: background execution unit with type, status, attempts, progress, cost
- `usage_event`: immutable record of billable or quota-relevant consumption
- `subscription`: workspace billing state from Stripe
```

- [ ] **Step 4: Save and review**

Run: `test -f docs/architecture/independent-saas-overview.md && test -f docs/architecture/service-boundaries.md && test -f docs/architecture/domain-glossary.md && echo OK`

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add docs/architecture/independent-saas-overview.md docs/architecture/service-boundaries.md docs/architecture/domain-glossary.md
git commit -m "docs: define independent saas target architecture"
```

### Task 2: Define The Independent Data Model

**Files:**
- Create: `docs/architecture/data-model.md`
- Create: `alembic/versions/<timestamp>_initial_saas_core.py`
- Create: `models/saas.py`
- Test: `tests/test_saas_models.py`

- [ ] **Step 1: Write the data model spec**

```md
# Initial SaaS Core Tables

## workspaces
- id UUID PK
- slug TEXT UNIQUE NOT NULL
- name TEXT NOT NULL
- plan TEXT NOT NULL DEFAULT 'free'
- created_at TIMESTAMPTZ NOT NULL

## users
- id UUID PK
- workspace_id UUID NOT NULL FK workspaces.id
- email TEXT NOT NULL
- full_name TEXT
- role TEXT NOT NULL DEFAULT 'owner'
- password_hash TEXT NULL
- created_at TIMESTAMPTZ NOT NULL

## projects
- id UUID PK
- workspace_id UUID NOT NULL FK workspaces.id
- kind TEXT NOT NULL
- title TEXT
- status TEXT NOT NULL DEFAULT 'draft'
- created_at TIMESTAMPTZ NOT NULL

## assets
- id UUID PK
- workspace_id UUID NOT NULL FK workspaces.id
- project_id UUID NULL FK projects.id
- storage_key TEXT NOT NULL UNIQUE
- mime_type TEXT NOT NULL
- size_bytes BIGINT NOT NULL
- kind TEXT NOT NULL
- created_at TIMESTAMPTZ NOT NULL

## jobs
- id UUID PK
- workspace_id UUID NOT NULL FK workspaces.id
- project_id UUID NULL FK projects.id
- kind TEXT NOT NULL
- status TEXT NOT NULL
- payload JSONB NOT NULL
- result JSONB NULL
- error_text TEXT NULL
- progress INTEGER NOT NULL DEFAULT 0
- attempts INTEGER NOT NULL DEFAULT 0
- created_at TIMESTAMPTZ NOT NULL
- started_at TIMESTAMPTZ NULL
- finished_at TIMESTAMPTZ NULL

## usage_events
- id UUID PK
- workspace_id UUID NOT NULL FK workspaces.id
- job_id UUID NULL FK jobs.id
- metric TEXT NOT NULL
- quantity NUMERIC NOT NULL
- unit TEXT NOT NULL
- source TEXT NOT NULL
- created_at TIMESTAMPTZ NOT NULL
```

- [ ] **Step 2: Write the failing model test**

```python
from sqlalchemy import inspect


def test_saas_core_tables_exist(sa_session):
    inspector = inspect(sa_session.bind)
    names = set(inspector.get_table_names())
    assert {"workspaces", "users", "projects", "assets", "jobs", "usage_events"} <= names
```

- [ ] **Step 3: Create the SQLAlchemy models**

```python
class Workspace(Base):
    __tablename__ = "workspaces"
    id = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug = mapped_column(String, unique=True, nullable=False)
    name = mapped_column(String, nullable=False)
    plan = mapped_column(String, nullable=False, default="free")
    created_at = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

- [ ] **Step 4: Create and run the migration**

Run: `alembic revision -m "initial saas core" && alembic upgrade head && pytest tests/test_saas_models.py -v`

Expected: migration applies cleanly and `1 passed`

- [ ] **Step 5: Commit**

```bash
git add docs/architecture/data-model.md models/saas.py alembic/versions tests/test_saas_models.py
git commit -m "feat: add independent saas core data model"
```

### Task 3: Replace In-Memory Jobs With Durable Queue Contracts

**Files:**
- Create: `jobs/repository.py`
- Create: `jobs/queue.py`
- Create: `jobs/worker.py`
- Modify: `app.py`
- Test: `tests/test_job_repository.py`
- Test: `tests/test_job_queue.py`

- [ ] **Step 1: Write the failing repository tests**

```python
def test_create_job_persists_payload(job_repo):
    job = job_repo.create(kind="clip_generate", workspace_id=workspace_id, payload={"source_asset_id": "a1"})
    loaded = job_repo.get(job.id)
    assert loaded.payload["source_asset_id"] == "a1"
    assert loaded.status == "queued"
```

- [ ] **Step 2: Implement the job repository**

```python
class JobRepository:
    def create(self, *, kind, workspace_id, payload, project_id=None):
        job = Job(
            kind=kind,
            workspace_id=workspace_id,
            project_id=project_id,
            payload=payload,
            status="queued",
        )
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job
```

- [ ] **Step 3: Implement the queue publisher contract**

```python
class QueuePublisher:
    def publish_job(self, job_id: str):
        self.redis.rpush("openshorts:jobs", job_id)
```

- [ ] **Step 4: Route `/api/process` through durable job creation**

```python
job = job_repo.create(
    kind="clip_generate",
    workspace_id=current_workspace.id,
    project_id=project.id,
    payload={"source_asset_id": asset.id, "options": normalized_options},
)
queue.publish_job(str(job.id))
return {"job_id": str(job.id), "status": "queued"}
```

- [ ] **Step 5: Verify persistence and queueing**

Run: `pytest tests/test_job_repository.py tests/test_job_queue.py -v`

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add jobs/repository.py jobs/queue.py jobs/worker.py app.py tests/test_job_repository.py tests/test_job_queue.py
git commit -m "feat: add durable saas job orchestration"
```

### Task 4: Build Independent Auth And Workspace Identity

**Files:**
- Create: `auth/models.py`
- Create: `auth/routes.py`
- Create: `auth/service.py`
- Modify: `dashboard/src/contexts/AuthContext.jsx`
- Modify: `dashboard/src/lib/api.js`
- Test: `tests/test_auth_routes.py`

- [ ] **Step 1: Write the failing auth test**

```python
def test_login_returns_bearer_token(client, seeded_user):
    res = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "secret123"})
    assert res.status_code == 200
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
```

- [ ] **Step 2: Implement password-based local auth first**

```python
@router.post("/api/auth/login")
async def login(payload: LoginInput, session=Depends(get_session)):
    user = auth_service.authenticate(session, payload.email, payload.password)
    token = auth_service.issue_access_token(user)
    return {"access_token": token, "token_type": "bearer", "user": auth_service.to_public_user(user)}
```

- [ ] **Step 3: Replace `BILLING_ENABLED`-driven frontend assumptions**

```jsx
const value = {
  loading,
  user,
  workspace,
  isSignedIn: !!user,
  login,
  logout,
  refreshSession,
};
```

- [ ] **Step 4: Verify auth flow**

Run: `pytest tests/test_auth_routes.py -v`

Expected: login, logout, and current-session tests pass

- [ ] **Step 5: Commit**

```bash
git add auth/models.py auth/routes.py auth/service.py dashboard/src/contexts/AuthContext.jsx dashboard/src/lib/api.js tests/test_auth_routes.py
git commit -m "feat: add independent saas auth foundation"
```

### Task 5: Design Billing And Quota Without `cloud/`

**Files:**
- Create: `billing/models.py`
- Create: `billing/routes.py`
- Create: `billing/stripe_webhooks.py`
- Create: `docs/architecture/billing-and-quota.md`
- Test: `tests/test_usage_ledger.py`
- Test: `tests/test_stripe_webhooks.py`

- [ ] **Step 1: Write the billing design doc**

```md
# Billing And Quota

- Stripe is the billing source of truth
- PostgreSQL is the application source of truth
- `usage_events` are append-only
- Monthly plan limits are computed from active subscription + add-ons
- Job reservation happens before execution
- Final commit or release happens on success/failure
```

- [ ] **Step 2: Write the failing quota test**

```python
def test_reserve_minutes_prevents_oversell(usage_service, workspace):
    usage_service.set_limit(workspace.id, minutes=100)
    usage_service.reserve(workspace.id, 60)
    with pytest.raises(QuotaExceeded):
        usage_service.reserve(workspace.id, 50)
```

- [ ] **Step 3: Implement independent usage reservation**

```python
class UsageService:
    def reserve(self, workspace_id, minutes):
        remaining = self.remaining_minutes(workspace_id)
        if remaining < minutes:
            raise QuotaExceeded(minutes_required=minutes, minutes_remaining=remaining)
        return self._write_usage_event(workspace_id, metric="minutes_reserved", quantity=minutes, unit="minute")
```

- [ ] **Step 4: Implement Stripe webhook ingestion**

```python
@router.post("/api/billing/webhooks/stripe")
async def stripe_webhook(request: Request):
    event = stripe.Webhook.construct_event(await request.body(), request.headers["stripe-signature"], webhook_secret)
    billing_service.handle_event(event)
    return {"ok": True}
```

- [ ] **Step 5: Verify quota and Stripe flow**

Run: `pytest tests/test_usage_ledger.py tests/test_stripe_webhooks.py -v`

Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add billing/models.py billing/routes.py billing/stripe_webhooks.py docs/architecture/billing-and-quota.md tests/test_usage_ledger.py tests/test_stripe_webhooks.py
git commit -m "feat: add independent billing and quota system"
```

### Task 6: Migrate The Frontend To A Real SaaS Workspace Shell

**Files:**
- Modify: `dashboard/src/App.jsx`
- Modify: `dashboard/src/components/HistoryTab.jsx`
- Modify: `dashboard/src/components/LoginModal.jsx`
- Modify: `dashboard/src/components/ProfileMenu.jsx`
- Create: `dashboard/src/components/WorkspaceSettings.jsx`
- Test: `dashboard/src/components/__tests__/workspace-shell.test.jsx`

- [ ] **Step 1: Write the failing frontend shell test**

```jsx
it("renders workspace navigation for signed-in users", async () => {
  render(<App />);
  expect(await screen.findByText(/settings/i)).toBeInTheDocument();
  expect(await screen.findByText(/history/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Move BYOK-only state behind workspace settings**

```jsx
const canUseServerGemini = config?.geminiConfigured === true;
const canUseBringYourOwnKey = workspace?.plan === "developer";
```

- [ ] **Step 3: Add workspace settings screen**

```jsx
export default function WorkspaceSettings() {
  return (
    <section className="card p-6">
      <p className="eyebrow mb-2">workspace</p>
      <h1 className="font-display text-2xl lowercase text-ink">settings</h1>
    </section>
  );
}
```

- [ ] **Step 4: Verify the managed shell**

Run: `npm test -- workspace-shell.test.jsx`

Expected: signed-in navigation and settings shell tests pass

- [ ] **Step 5: Commit**

```bash
git add dashboard/src/App.jsx dashboard/src/components/HistoryTab.jsx dashboard/src/components/LoginModal.jsx dashboard/src/components/ProfileMenu.jsx dashboard/src/components/WorkspaceSettings.jsx dashboard/src/components/__tests__/workspace-shell.test.jsx
git commit -m "feat: add managed saas frontend shell"
```

### Task 7: Productionize For VPS Deployment

**Files:**
- Create: `docker-compose.saas.yml`
- Create: `ops/caddy/Caddyfile`
- Create: `ops/env/api.env.example`
- Create: `ops/env/worker.env.example`
- Create: `docs/deploy/vps-saas.md`

- [ ] **Step 1: Write the VPS deployment topology**

```yaml
services:
  api:
    image: openshorts-api:latest
  worker-media:
    image: openshorts-api:latest
    command: python -m jobs.worker
  renderer:
    image: openshorts-renderer:latest
  postgres:
    image: postgres:16
  redis:
    image: redis:7
  caddy:
    image: caddy:2
```

- [ ] **Step 2: Write the deployment guide**

```md
# VPS SaaS Deployment

1. Provision Ubuntu VPS
2. Install Docker and Docker Compose
3. Configure DNS and TLS
4. Populate `ops/env/*.env`
5. Run migrations
6. Start services
7. Validate health checks
```

- [ ] **Step 3: Validate the compose file**

Run: `docker compose -f docker-compose.saas.yml config > /tmp/openshorts-saas-compose.yaml && test -s /tmp/openshorts-saas-compose.yaml && echo OK`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add docker-compose.saas.yml ops/caddy/Caddyfile ops/env/api.env.example ops/env/worker.env.example docs/deploy/vps-saas.md
git commit -m "ops: add independent saas vps deployment"
```

## Recommended Order

1. Task 1 first
2. Split follow-up execution into separate implementation plans for Tasks 2-7
3. Ship Account/Auth + Data Model before touching billing
4. Ship Durable Jobs + Object Storage before exposing public signup
5. Ship Billing only after quota enforcement is already correct without Stripe

## Risks To Avoid

- Do not reuse `cloud/` models, routes, helpers, or migrations
- Do not keep in-memory job state for tenant-visible history
- Do not use local disk as the long-term source of truth in SaaS mode
- Do not couple billing correctness to frontend state
- Do not store production provider secrets only in browser `localStorage`

## Deliverable Check

- Independent SaaS compiles and runs with `BILLING_ENABLED` permanently off
- Hosted auth, projects, jobs, history, and billing work without importing `cloud/`
- Clip generation and rendering use durable storage and queue-backed execution
- VPS deployment works with PostgreSQL, Redis, and S3-compatible storage


from saas.database import Base
from saas.models import Asset, Job, Project, UsageEvent, User, Workspace


def test_saas_base_metadata_exists():
    assert Base.metadata is not None


def test_saas_models_export_core_entities():
    assert Workspace.__tablename__ == "workspaces"
    assert User.__tablename__ == "users"
    assert Project.__tablename__ == "projects"
    assert Asset.__tablename__ == "assets"
    assert Job.__tablename__ == "jobs"
    assert UsageEvent.__tablename__ == "usage_events"


def test_saas_model_metadata_registers_core_tables():
    assert {
        "workspaces",
        "users",
        "projects",
        "assets",
        "jobs",
        "usage_events",
    }.issubset(Base.metadata.tables)


def test_saas_model_columns_match_core_contract():
    workspace_columns = Workspace.__table__.c
    user_columns = User.__table__.c
    asset_columns = Asset.__table__.c
    job_columns = Job.__table__.c
    usage_event_columns = UsageEvent.__table__.c

    assert workspace_columns.slug.unique is True
    assert workspace_columns.plan.default.arg == "free"
    assert workspace_columns.created_at.server_default is not None

    assert user_columns.workspace_id.index is True
    assert user_columns.email.index is True
    assert user_columns.role.default.arg == "owner"
    assert user_columns.password_hash.nullable is False

    assert asset_columns.storage_key.unique is True
    assert asset_columns.project_id.nullable is True
    assert asset_columns.size_bytes.nullable is False

    assert job_columns.status.default.arg == "queued"
    assert job_columns.payload.nullable is False
    assert job_columns.result.nullable is True
    assert job_columns.progress.default.arg == 0
    assert job_columns.attempts.default.arg == 0

    assert usage_event_columns.job_id.nullable is True
    assert usage_event_columns.quantity.type.precision == 12
    assert usage_event_columns.quantity.type.scale == 3

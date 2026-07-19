import asyncio
import os
import uuid

from starlette.requests import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

import app as app_module
from saas.auth import create_access_token
from saas.database import Base
from saas.models import Workspace
import saas.storage as storage_module


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def test_persist_saas_source_asset_copies_file_and_records_asset(tmp_path, monkeypatch):
    async def scenario() -> None:
        db_file = tmp_path / "saas-source-assets.sqlite3"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file}")
        await _create_schema(engine)
        sessionmaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

        async with sessionmaker() as session:
            workspace = Workspace(slug="acme", name="Acme", plan="free")
            session.add(workspace)
            await session.commit()
            workspace_id = workspace.id

        source_file = tmp_path / "demo.mp4"
        source_file.write_bytes(b"demo-video")

        source_root = tmp_path / "saas_uploads"
        source_root.mkdir()

        monkeypatch.setattr(storage_module, "SAAS_SOURCE_DIR", str(source_root))
        monkeypatch.setattr(app_module, "get_sessionmaker", lambda: sessionmaker)

        token = create_access_token(user_id=uuid.uuid4(), workspace_id=workspace_id)
        request = Request(
            {
                "type": "http",
                "headers": [(b"authorization", f"Bearer {token}".encode("utf-8"))],
            }
        )

        asset_id = await app_module._persist_saas_source_asset(
            request=request,
            input_path=str(source_file),
            source_name="demo.mp4",
            mime_type="video/mp4",
        )

        assert asset_id is not None

        async with sessionmaker() as session:
            result = await session.execute(text("select id, storage_key, mime_type, size_bytes from assets"))
            rows = result.fetchall()
            assert len(rows) == 1
            row = rows[0]
            assert uuid.UUID(str(row[0])) == uuid.UUID(str(asset_id))
            assert row[2] == "video/mp4"
            assert row[3] == len(b"demo-video")

            copied_path = storage_module.resolve_source_asset_path(row[1])
            assert os.path.exists(copied_path)
            with open(copied_path, "rb") as copied_file:
                assert copied_file.read() == b"demo-video"

        await engine.dispose()

    asyncio.run(scenario())

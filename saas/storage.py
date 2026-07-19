from __future__ import annotations

import os
from uuid import UUID


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAAS_SOURCE_DIR = os.path.join(PROJECT_ROOT, "saas_uploads")
os.makedirs(SAAS_SOURCE_DIR, exist_ok=True)


def sanitize_asset_filename(filename: str) -> str:
    safe_name = os.path.basename(filename or "upload") or "upload"
    return safe_name.replace(os.sep, "_")


def build_source_storage_key(*, workspace_id: UUID | str, asset_id: UUID | str, filename: str) -> str:
    return os.path.join(str(workspace_id), f"{asset_id}_{sanitize_asset_filename(filename)}")


def resolve_source_asset_path(storage_key: str) -> str:
    candidate = os.path.abspath(os.path.join(SAAS_SOURCE_DIR, storage_key))
    root = os.path.abspath(SAAS_SOURCE_DIR)
    if os.path.commonpath([root, candidate]) != root:
        raise ValueError("Invalid SaaS asset path")
    return candidate

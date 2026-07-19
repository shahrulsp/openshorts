import os
import sys

os.environ.setdefault("SAAS_ENABLED", "true")
os.environ.setdefault("SAAS_DATABASE_URL", "sqlite+aiosqlite:///./test_saas.db")
os.environ.setdefault("SAAS_JWT_SECRET", "test-secret")

# Make the repo root importable so tests can import the app modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

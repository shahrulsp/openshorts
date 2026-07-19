from dataclasses import dataclass
import os


def _flag(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class SaaSSettings:
    enabled: bool
    database_url: str
    jwt_secret: str
    jwt_issuer: str
    access_token_ttl_minutes: int


def load_saas_settings() -> SaaSSettings:
    return SaaSSettings(
        enabled=_flag("SAAS_ENABLED"),
        database_url=os.environ.get("SAAS_DATABASE_URL") or os.environ.get("DATABASE_URL", ""),
        jwt_secret=os.environ.get("SAAS_JWT_SECRET", "dev-insecure-change-me"),
        jwt_issuer=os.environ.get("SAAS_JWT_ISSUER", "openshorts-local"),
        access_token_ttl_minutes=int(os.environ.get("SAAS_ACCESS_TOKEN_TTL_MINUTES", "1440")),
    )

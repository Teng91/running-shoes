"""Typed runtime configuration loaded once from environment variables."""

import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# HS256 keys shorter than the hash output are brute-forceable (RFC 7518 §3.2).
MIN_SECRET_KEY_BYTES = 32
# Development-only signing key; production refuses to start without SECRET_KEY.
DEV_FALLBACK_SECRET_KEY = "development-only-insecure-secret-key-change-me"


def _positive_int(values: Mapping[str, str], name: str, default: int) -> int:
    return max(1, int(values.get(name, str(default))))


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    secret_key: str
    database_dir: Path
    database_url: str
    frontend_dir: Path
    seed_data: bool
    migration_password: str | None
    fly_app_name: str | None
    max_registered_users: int
    max_shoes_per_user: int
    max_runs_per_user: int
    agent_rate_limit_per_minute: int
    agent_ip_rate_limit_per_minute: int
    agent_global_rate_limit_per_minute: int
    auth_rate_limit_per_minute: int
    auth_global_rate_limit_per_minute: int
    model_refresh_cooldown_seconds: int
    model_refresh_global_per_minute: int
    llm_max_output_tokens: int
    openrouter_default_model: str | None
    max_strava_csv_bytes: int = 10 * 1024 * 1024
    max_strava_csv_rows: int = 50_000
    max_strava_import_history_per_user: int = 50

    @property
    def is_production(self) -> bool:
        return self.environment.casefold() != "development"

    @property
    def is_fly_runtime(self) -> bool:
        return bool(self.fly_app_name)

    @property
    def max_strava_request_bytes(self) -> int:
        return self.max_strava_csv_bytes + 1024 * 1024

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if values is None else values
        root = Path(__file__).resolve().parent.parent
        database_dir = Path(env.get("DB_DIR", str(root)))
        frontend_dir = Path(env.get("FRONTEND_DIR", str(root / "frontend")))
        return cls(
            environment=env.get("ENVIRONMENT", "development"),
            secret_key=env.get("SECRET_KEY", ""),
            database_dir=database_dir,
            database_url=env.get("DATABASE_URL", f"sqlite:///{database_dir}/shoes.db"),
            frontend_dir=frontend_dir,
            seed_data=env.get("SEED_DATA", "").casefold() == "true",
            migration_password=env.get("MIGRATION_PASSWORD") or None,
            fly_app_name=env.get("FLY_APP_NAME") or None,
            max_registered_users=_positive_int(env, "MAX_REGISTERED_USERS", 100),
            max_shoes_per_user=_positive_int(env, "MAX_SHOES_PER_USER", 500),
            max_runs_per_user=_positive_int(env, "MAX_RUNS_PER_USER", 5000),
            agent_rate_limit_per_minute=_positive_int(env, "AGENT_RATE_LIMIT_PER_MINUTE", 20),
            agent_ip_rate_limit_per_minute=_positive_int(env, "AGENT_IP_RATE_LIMIT_PER_MINUTE", 30),
            agent_global_rate_limit_per_minute=_positive_int(env, "AGENT_GLOBAL_RATE_LIMIT_PER_MINUTE", 120),
            auth_rate_limit_per_minute=_positive_int(env, "AUTH_RATE_LIMIT_PER_MINUTE", 120),
            auth_global_rate_limit_per_minute=_positive_int(env, "AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE", 300),
            model_refresh_cooldown_seconds=_positive_int(env, "MODEL_REFRESH_COOLDOWN_SECONDS", 60),
            model_refresh_global_per_minute=_positive_int(env, "MODEL_REFRESH_GLOBAL_PER_MINUTE", 10),
            llm_max_output_tokens=max(256, int(env.get("LLM_MAX_OUTPUT_TOKENS", "4096"))),
            openrouter_default_model=env.get("OR_MODEL") or None,
        )


def megabytes_label(size: int) -> str:
    """Human-readable limit for error messages, derived from the configured bytes."""
    return f"{size / (1024 * 1024):g} MB"


def runtime_settings(config: Settings) -> Settings:
    """Validate the signing secret for this environment before serving requests.

    Production refuses a missing or short SECRET_KEY; development gets a loud,
    deterministic fallback so local runs and tests can sign tokens.
    """
    if config.is_production:
        if not config.secret_key:
            raise RuntimeError("SECRET_KEY environment variable is required in production")
        if len(config.secret_key.encode("utf-8")) < MIN_SECRET_KEY_BYTES:
            raise RuntimeError(f"SECRET_KEY must be at least {MIN_SECRET_KEY_BYTES} bytes in production")
        return config
    if config.secret_key:
        return config
    warnings.warn("Using fallback SECRET_KEY — set the SECRET_KEY env var in production!", stacklevel=2)
    return replace(config, secret_key=DEV_FALLBACK_SECRET_KEY)


def default_secret_key() -> str:
    """Signing key of the default (environment) settings, for scripts and tests."""
    return settings.secret_key or DEV_FALLBACK_SECRET_KEY


settings = Settings.from_env()

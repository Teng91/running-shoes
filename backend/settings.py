"""Typed runtime configuration loaded once from environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


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


settings = Settings.from_env()

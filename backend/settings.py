"""Typed runtime configuration loaded once from environment variables."""

import os
import warnings
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# HS256 keys shorter than the hash output are brute-forceable (RFC 7518 §3.2).
MIN_SECRET_KEY_BYTES = 32
# Rate-limit buckets older than this are deleted, so no window may be longer.
# The daily AI budget (SPEC-071) is the longest window.
RATE_LIMIT_BUCKET_RETENTION_SECONDS = 24 * 3600
DAILY_WINDOW_SECONDS = 24 * 3600
# Cooldowns stay short even though buckets now live for a day.
MAX_MODEL_REFRESH_COOLDOWN_SECONDS = 3600
# Development-only signing key; production refuses to start without SECRET_KEY.
DEV_FALLBACK_SECRET_KEY = "development-only-insecure-secret-key-change-me"


def _positive_int(values: Mapping[str, str], name: str, default: int) -> int:
    return max(1, int(values.get(name, str(default))))


REGISTRATION_MODES = ("invite", "open", "closed")


def _registration_mode(values: Mapping[str, str]) -> str:
    """Invite-only unless explicitly opened or closed (SPEC-075); unknown values fail closed."""
    mode = values.get("REGISTRATION_MODE", "invite").strip().casefold()
    return mode if mode in REGISTRATION_MODES else "closed"


_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


def account_name_key(name: str) -> str:
    """An account name's identity: trimmed, with only A–Z lowered, like SQLite's lower() (SPEC-093).

    Admin names use the same rule (SPEC-130), so "Straße" and "STRASSE", two different accounts,
    can never both match one admin name the way Python's casefold() would make them.
    """
    return name.strip().translate(_ASCII_LOWER)


def _admin_usernames(values: Mapping[str, str]) -> frozenset[str]:
    return frozenset(account_name_key(name) for name in values.get("ADMIN_USERNAMES", "").split(",") if name.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    secret_key: str = field(repr=False)
    database_dir: Path
    database_url: str
    frontend_dir: Path
    seed_data: bool
    migration_password: str | None = field(repr=False)
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
    # SPEC-142: every other /api/ request body (JSON, sign-in forms, chat turns).
    max_api_body_bytes: int = 1024 * 1024
    max_strava_csv_rows: int = 50_000
    max_strava_import_history_per_user: int = 50
    # Each file or mode change in the restore panel previews again; allow normal use.
    restore_preview_rate_limit_per_minute: int = 20
    restore_preview_global_rate_limit_per_minute: int = 60
    # Daily LLM budget (SPEC-071): bounds what open registration can spend.
    agent_daily_limit_per_user: int = 20
    agent_global_daily_limit: int = 200
    # Every /api/ request per client address and minute (SPEC-073); normal use stays far below.
    api_rate_limit_per_minute: int = 600
    # Strava CSV preview/import per account and minute (SPEC-074).
    strava_upload_rate_limit_per_minute: int = 10
    # SPEC-075: who may register, and which accounts manage invites and password resets.
    registration_mode: str = "invite"
    admin_usernames: frozenset[str] = frozenset()
    # SPEC-079: Gmail SMTP with an app password; email features are off without both.
    smtp_username: str | None = None
    smtp_password: str | None = field(default=None, repr=False)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    # SPEC-093: injected into backend.llm by create_app instead of read there at import time.
    openrouter_api_key: str | None = field(default=None, repr=False)

    @property
    def mail_enabled(self) -> bool:
        return bool(self.smtp_username and self.smtp_password)

    def is_admin(self, username: str) -> bool:
        return account_name_key(username) in self.admin_usernames

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
            # SPEC-074: each attempt is a ~0.2-0.3 s bcrypt check on the one shared CPU,
            # so the site-wide budget stays well under a minute of CPU per minute.
            auth_rate_limit_per_minute=_positive_int(env, "AUTH_RATE_LIMIT_PER_MINUTE", 20),
            auth_global_rate_limit_per_minute=_positive_int(env, "AUTH_GLOBAL_RATE_LIMIT_PER_MINUTE", 60),
            model_refresh_cooldown_seconds=min(
                MAX_MODEL_REFRESH_COOLDOWN_SECONDS,
                _positive_int(env, "MODEL_REFRESH_COOLDOWN_SECONDS", 60),
            ),
            model_refresh_global_per_minute=_positive_int(env, "MODEL_REFRESH_GLOBAL_PER_MINUTE", 10),
            llm_max_output_tokens=max(256, int(env.get("LLM_MAX_OUTPUT_TOKENS", "4096"))),
            openrouter_default_model=env.get("OR_MODEL") or None,
            restore_preview_rate_limit_per_minute=_positive_int(env, "RESTORE_PREVIEW_RATE_LIMIT_PER_MINUTE", 20),
            restore_preview_global_rate_limit_per_minute=_positive_int(
                env, "RESTORE_PREVIEW_GLOBAL_RATE_LIMIT_PER_MINUTE", 60
            ),
            agent_daily_limit_per_user=_positive_int(env, "AGENT_DAILY_LIMIT_PER_USER", 20),
            agent_global_daily_limit=_positive_int(env, "AGENT_GLOBAL_DAILY_LIMIT", 200),
            api_rate_limit_per_minute=_positive_int(env, "API_RATE_LIMIT_PER_MINUTE", 600),
            strava_upload_rate_limit_per_minute=_positive_int(env, "STRAVA_UPLOAD_RATE_LIMIT_PER_MINUTE", 10),
            registration_mode=_registration_mode(env),
            admin_usernames=_admin_usernames(env),
            smtp_username=(env.get("SMTP_USERNAME") or "").strip() or None,
            # Google shows app passwords in groups of four; spaces are not part of them.
            smtp_password=(env.get("SMTP_PASSWORD") or "").replace(" ", "") or None,
            smtp_host=env.get("SMTP_HOST", "smtp.gmail.com"),
            smtp_port=_positive_int(env, "SMTP_PORT", 587),
            openrouter_api_key=(env.get("OPENROUTER_API_KEY") or "").strip() or None,
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

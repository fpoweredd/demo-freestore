from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _to_int(value: str, default: int = 0) -> int:
    try:
        return int((value or "").strip())
    except Exception:
        return default


def _resolve_dotenv_path(dotenv_path: str) -> Path | None:
    direct = Path(dotenv_path)
    candidates: list[Path] = []
    if direct.is_absolute():
        candidates.append(direct)
    else:
        candidates.append(Path.cwd() / direct)
        module_dir = Path(__file__).resolve().parent
        candidates.append(module_dir / direct)
        for parent in module_dir.parents:
            candidates.append(parent / direct)
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _load_dotenv(dotenv_path: str) -> None:
    path = _resolve_dotenv_path(dotenv_path)
    if path is None:
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        k = key.strip()
        v = value.strip()
        if (len(v) >= 2) and ((v[0] == v[-1]) and v[0] in ("'", '"')):
            v = v[1:-1]
        os.environ.setdefault(k, v)


_load_dotenv(".env")


@dataclass(frozen=True)
class BotSettings:
    token: str
    username: str
    database_url: str
    start_cooldown_seconds: int
    internal_api_key: str
    internal_api_bind: str
    public_site_url: str
    healthcheck_initial_delay_seconds: int
    healthcheck_interval_seconds: int
    healthcheck_timeout_seconds: int
    forum_chat_id: int
    topic_bot_start: int
    topic_manual_orders: int
    topic_preorders: int
    topic_errors: int
    topic_logs: int
    topic_signups: int
    topic_topups: int
    topic_orders: int
    topic_general: int

    @property
    def start_button_url(self) -> str:
        username = (self.username or "").strip().lstrip("@")
        return f"https://t.me/{username}?startapp"


def _build_database_url() -> str:
    db_engine = (os.getenv("DB_ENGINE", "sqlite") or "sqlite").strip().lower()
    pg_db = (os.getenv("POSTGRES_DB", "") or "").strip()
    pg_user = (os.getenv("POSTGRES_USER", "") or "").strip()
    pg_password = (os.getenv("POSTGRES_PASSWORD", "") or "").strip()
    pg_host = (os.getenv("POSTGRES_HOST", "") or "").strip()
    pg_port = (os.getenv("POSTGRES_PORT", "5432") or "5432").strip()
    if db_engine == "postgres" and pg_db and pg_user and pg_host:
        return (
            f"postgresql+asyncpg://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_db}"
        )

    repo_root = Path(__file__).resolve().parents[3]
    sqlite_name = (os.getenv("SQLITE_NAME", "") or "").strip()
    if sqlite_name:
        raw_sqlite_path = Path(sqlite_name)
        if raw_sqlite_path.is_absolute():
            sqlite_path = raw_sqlite_path
        else:
            sqlite_path = (repo_root / raw_sqlite_path).resolve()
    else:
        # Keep default aligned with Django sqlite location.
        sqlite_path = (repo_root / "services" / "django" / "db.sqlite3").resolve()
    return f"sqlite+aiosqlite:///{sqlite_path.as_posix()}"


def get_settings() -> BotSettings:
    return BotSettings(
        token=(os.getenv("TELEGRAM_BOT_TOKEN", "") or "").strip(),
        username=(os.getenv("TELEGRAM_BOT_USERNAME", "") or "").strip(),
        database_url=_build_database_url(),
        start_cooldown_seconds=max(
            0, _to_int(os.getenv("START_COOLDOWN_SECONDS", "300"), 300)
        ),
        internal_api_key=(os.getenv("BOT_INTERNAL_API_KEY", "") or "").strip(),
        internal_api_bind=(
            os.getenv("BOT_INTERNAL_API_BIND", "0.0.0.0:8091") or "0.0.0.0:8091"
        ).strip(),
        public_site_url=(os.getenv("PUBLIC_SITE_URL", "") or "").strip().rstrip("/"),
        healthcheck_initial_delay_seconds=max(
            0, _to_int(os.getenv("HEALTHCHECK_INITIAL_DELAY_SECONDS", "600"), 600)
        ),
        healthcheck_interval_seconds=max(
            60, _to_int(os.getenv("HEALTHCHECK_INTERVAL_SECONDS", "3600"), 3600)
        ),
        healthcheck_timeout_seconds=max(
            1, _to_int(os.getenv("HEALTHCHECK_TIMEOUT_SECONDS", "10"), 10)
        ),
        forum_chat_id=_to_int(os.getenv("TG_FORUM_CHAT_ID", "0")),
        topic_bot_start=_to_int(os.getenv("TG_TOPIC_BOT_START", "0")),
        topic_manual_orders=_to_int(os.getenv("TG_TOPIC_MANUAL_ORDERS", "0")),
        topic_preorders=_to_int(os.getenv("TG_TOPIC_PREORDERS", "0")),
        topic_errors=_to_int(os.getenv("TG_TOPIC_ERRORS", "0")),
        topic_logs=_to_int(os.getenv("TG_TOPIC_LOGS", "0")),
        topic_signups=_to_int(os.getenv("TG_TOPIC_SIGNUPS", "0")),
        topic_topups=_to_int(os.getenv("TG_TOPIC_TOPUPS", "0")),
        topic_orders=_to_int(os.getenv("TG_TOPIC_ORDERS", "0")),
        topic_general=_to_int(os.getenv("TG_TOPIC_GENERAL", "1")),
    )

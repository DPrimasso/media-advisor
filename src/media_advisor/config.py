"""Settings via pydantic-settings — reads from env / .env file."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Multi-file .env: pydantic-settings loads in order; **later files override earlier**.
# Put optional `cwd/.env` first, then repo `.env` last so the project `.env` always wins
# (avoids e.g. `C:\Users\you\.env` with empty TRANSCRIPT_API_KEY wiping keys from the repo).
_repo_root = Path(__file__).resolve().parents[2]
_repo_env = (_repo_root / ".env").resolve()
_cwd_env = Path(".env").resolve()
_env_paths: list[Path] = []
if _cwd_env.is_file() and _cwd_env != _repo_env:
    _env_paths.append(_cwd_env)
if _repo_env.is_file():
    _env_paths.append(_repo_env)
_env_files: tuple[str, ...] = tuple(str(p) for p in _env_paths)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_env_files if _env_files else (".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API keys
    transcript_api_key: str = Field(default="", alias="TRANSCRIPT_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    telegram_thread_id: int | None = Field(default=None, alias="TELEGRAM_THREAD_ID")
    # Destinazione separata per report costi post-sync (es. DM personale)
    telegram_personal_chat_id: str = Field(default="", alias="TELEGRAM_PERSONAL_CHAT_ID")
    telegram_personal_thread_id: int | None = Field(
        default=None, alias="TELEGRAM_PERSONAL_THREAD_ID"
    )

    # Stima costi (USD per 1M token / per chiamata Transcript API a pagamento). None = non mostrare importo.
    openai_input_usd_per_1m: float | None = Field(
        default=None, alias="MEDIA_ADVISOR_OPENAI_INPUT_USD_PER_1M"
    )
    openai_output_usd_per_1m: float | None = Field(
        default=None, alias="MEDIA_ADVISOR_OPENAI_OUTPUT_USD_PER_1M"
    )
    transcript_api_usd_per_paid_call: float | None = Field(
        default=None, alias="MEDIA_ADVISOR_TRANSCRIPT_API_USD_PER_CALL"
    )

    # Paths (relative to project root by default)
    root_dir: Path = Field(default=Path("."), alias="MEDIA_ADVISOR_ROOT")
    channels_dir: Path | None = Field(default=None, alias="MEDIA_ADVISOR_CHANNELS_DIR")
    analysis_dir: Path | None = Field(default=None, alias="MEDIA_ADVISOR_ANALYSIS_DIR")
    transcripts_dir: Path | None = Field(default=None, alias="MEDIA_ADVISOR_TRANSCRIPTS_DIR")

    # SQLite (default: <root>/data/media_advisor.sqlite). Override with full URL, e.g. sqlite:////path/to/db.sqlite
    database_url: str | None = Field(default=None, alias="MEDIA_ADVISOR_DATABASE_URL")

    # When False, daily mercato reports are only persisted in SQLite (no reports/*.md/json sidecars).
    export_report_files: bool = Field(default=True, alias="MEDIA_ADVISOR_EXPORT_REPORT_FILES")

    # When non-empty, POST /api/sync*, /api/fetch-now require header X-Media-Advisor-Sync with this value.
    sync_secret: str = Field(default="", alias="MEDIA_ADVISOR_SYNC_SECRET")

    # Comma-separated CORS origins for the FastAPI app; empty or unset = allow all (*).
    cors_origins: str = Field(default="", alias="MEDIA_ADVISOR_CORS_ORIGINS")

    # Pipeline
    llm_model: str = Field(default="gpt-4.1-mini", alias="MEDIA_ADVISOR_LLM_MODEL")
    max_segments: int = Field(default=12, alias="MEDIA_ADVISOR_MAX_SEGMENTS")
    max_claims: int = Field(default=12, alias="MEDIA_ADVISOR_MAX_CLAIMS")

    # Transcript API
    transcript_api_base_url: str = Field(
        default="https://transcriptapi.com/api/v2",
        alias="TRANSCRIPT_API_BASE_URL",
    )
    transcript_api_max_retries: int = Field(default=3, alias="TRANSCRIPT_API_MAX_RETRIES")

    @field_validator("telegram_thread_id", "telegram_personal_thread_id", mode="before")
    @classmethod
    def _empty_thread_id_to_none(cls, value: str | int | None) -> str | int | None:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                return None
            return stripped
        return value

    @field_validator(
        "openai_input_usd_per_1m",
        "openai_output_usd_per_1m",
        "transcript_api_usd_per_paid_call",
        mode="before",
    )
    @classmethod
    def _empty_pricing_to_none(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    def get_channels_dir(self) -> Path:
        return self.channels_dir or (self.root_dir / "channels")

    def get_analysis_dir(self) -> Path:
        return self.analysis_dir or (self.root_dir / "data" / "analysis")

    def get_transcripts_dir(self) -> Path:
        return self.transcripts_dir or (self.root_dir / "data" / "transcripts")

    def get_database_url(self, *, data_root: Path | None = None) -> str:
        """Resolved SQLAlchemy URL. When unset, uses SQLite under data_root/data/media_advisor.sqlite."""
        if self.database_url and self.database_url.strip():
            return self.database_url.strip()
        base = (data_root if data_root is not None else self.root_dir).resolve()
        db_path = (base / "data" / "media_advisor.sqlite").resolve()
        return f"sqlite:///{db_path.as_posix()}"

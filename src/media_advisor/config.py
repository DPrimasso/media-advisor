"""Settings via pydantic-settings — reads from env / .env file."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API keys
    transcript_api_key: str = Field(default="", alias="TRANSCRIPT_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # Paths (relative to project root by default)
    root_dir: Path = Field(default=Path("."), alias="MEDIA_ADVISOR_ROOT")
    channels_dir: Path | None = Field(default=None, alias="MEDIA_ADVISOR_CHANNELS_DIR")
    analysis_dir: Path | None = Field(default=None, alias="MEDIA_ADVISOR_ANALYSIS_DIR")
    transcripts_dir: Path | None = Field(default=None, alias="MEDIA_ADVISOR_TRANSCRIPTS_DIR")

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

    def get_channels_dir(self) -> Path:
        return self.channels_dir or (self.root_dir / "channels")

    def get_analysis_dir(self) -> Path:
        return self.analysis_dir or (self.root_dir / "data" / "analysis")

    def get_transcripts_dir(self) -> Path:
        return self.transcripts_dir or (self.root_dir / "data" / "transcripts")

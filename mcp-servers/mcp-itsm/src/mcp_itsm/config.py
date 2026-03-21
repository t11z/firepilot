"""Environment variable loading and server configuration for mcp-itsm."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server configuration loaded from environment variables.

    In live mode, ITSM_GITHUB_TOKEN and ITSM_GITHUB_REPO must be non-empty.
    In demo mode, GitHub credentials are not required.
    """

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    firepilot_env: str = "demo"
    itsm_github_token: str = ""
    itsm_github_repo: str = ""
    itsm_approval_timeout_seconds: int = 3600
    itsm_poll_interval_seconds: int = 60
    # Path where write_config_file writes YAML artefacts (ADR-0015).
    # Set by the workflow via OUTPUT_DIR environment variable.
    # Defaults to empty string; the tool returns OUTPUT_DIR_NOT_SET if unset.
    output_dir: str = ""

    @model_validator(mode="after")
    def validate_live_credentials(self) -> "Settings":
        """Validate that live mode credentials are present when running in live mode."""
        if self.firepilot_env == "live":
            missing = [
                name
                for name, value in [
                    ("ITSM_GITHUB_TOKEN", self.itsm_github_token),
                    ("ITSM_GITHUB_REPO", self.itsm_github_repo),
                ]
                if not value
            ]
            if missing:
                raise ValueError(
                    f"Live mode requires non-empty values for: {', '.join(missing)}"
                )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached server settings loaded from environment."""
    return Settings()

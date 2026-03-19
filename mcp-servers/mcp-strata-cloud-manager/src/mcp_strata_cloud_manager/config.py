"""Environment variable loading and server configuration for mcp-strata-cloud-manager."""

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server configuration loaded from environment variables.

    In live mode, SCM_CLIENT_ID, SCM_CLIENT_SECRET, and SCM_TSG_ID must be non-empty.
    In demo mode, SCM credentials are not required.
    """

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    firepilot_env: str = "demo"
    scm_client_id: str = ""
    scm_client_secret: str = ""
    scm_tsg_id: str = ""
    scm_api_base_url: str = "https://api.strata.paloaltonetworks.com"
    scm_token_url: str = "https://auth.apps.paloaltonetworks.com/oauth2/access_token"
    scm_push_timeout_seconds: int = 300

    @model_validator(mode="after")
    def validate_live_credentials(self) -> "Settings":
        """Validate that live mode credentials are present when running in live mode."""
        if self.firepilot_env == "live":
            missing = [
                name
                for name, value in [
                    ("SCM_CLIENT_ID", self.scm_client_id),
                    ("SCM_CLIENT_SECRET", self.scm_client_secret),
                    ("SCM_TSG_ID", self.scm_tsg_id),
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

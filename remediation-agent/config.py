"""Configuration for the OpenShift Remediation Agent."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Agent configuration loaded from environment variables."""

    AGENT_NAME: str = "openshift-remediation-agent"
    AGENT_HOST: str = "0.0.0.0"
    AGENT_PORT: int = 8080
    AGENT_EXTERNAL_URL: str = "http://localhost:8080"

    ALLOWED_NAMESPACES: str = ""
    DRY_RUN: bool = False
    LOG_LEVEL: str = "INFO"

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    @property
    def allowed_namespaces_list(self) -> list[str]:
        """Return ALLOWED_NAMESPACES as a list of strings."""
        if not self.ALLOWED_NAMESPACES:
            return []
        return [ns.strip() for ns in self.ALLOWED_NAMESPACES.split(",") if ns.strip()]


settings = Settings()

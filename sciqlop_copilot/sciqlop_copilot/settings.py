"""Copilot backend settings — GitHub OAuth token in keyring, tuning in YAML."""
from pydantic import Field, field_validator
from SciQLop.components.settings import SettingsCategory
from SciQLop.components.settings.backend import ConfigEntry

_KEYRING_SERVICE = "sciqlop_copilot"
_KEYRING_USERNAME = "github_token"


def load_github_token() -> str:
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME) or ""
    except Exception:
        return ""


def save_github_token(token: str) -> None:
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, token)
    except Exception:
        pass


def clear_github_token() -> None:
    try:
        import keyring
        keyring.delete_password(_KEYRING_SERVICE, _KEYRING_USERNAME)
    except Exception:
        pass


class CopilotSettings(ConfigEntry):
    category = SettingsCategory.PLUGINS
    subcategory = "GitHub Copilot"

    temperature: float = Field(
        default=0.3,
        description="Sampling temperature (0 = deterministic, 2 = max randomness)",
        ge=0.0,
        le=2.0,
    )
    top_p: float = Field(
        default=1.0,
        description="Nucleus sampling — only consider tokens within this cumulative probability",
        ge=0.0,
        le=1.0,
    )
    max_completion_tokens: int = Field(
        default=4096,
        description="Maximum number of tokens in the response (0 = no limit)",
        ge=0,
    )

    # Clamp out-of-range persisted values so stale or hand-edited YAML
    # doesn't crash the settings panel.
    @field_validator("top_p", mode="before")
    @classmethod
    def _clamp_top_p(cls, v):
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            return v

    @field_validator("temperature", mode="before")
    @classmethod
    def _clamp_temperature(cls, v):
        try:
            return max(0.0, min(2.0, float(v)))
        except (TypeError, ValueError):
            return v

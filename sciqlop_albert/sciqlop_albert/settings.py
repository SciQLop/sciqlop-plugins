"""Albert backend settings — API key stored in the system keyring."""
from pydantic import Field
from SciQLop.components.settings import SettingsCategory
from SciQLop.components.settings.backend import ConfigEntry

_KEYRING_SERVICE = "sciqlop_albert"
_KEYRING_USERNAME = "api_key"


def _load_api_key() -> str:
    try:
        import keyring
        return keyring.get_password(_KEYRING_SERVICE, _KEYRING_USERNAME) or ""
    except Exception:
        return ""


def _save_api_key(key: str) -> None:
    try:
        import keyring
        keyring.set_password(_KEYRING_SERVICE, _KEYRING_USERNAME, key)
    except Exception:
        pass


class AlbertSettings(ConfigEntry):
    category = SettingsCategory.PLUGINS
    subcategory = "Albert"

    base_url: str = Field(
        default="https://albert.api.etalab.gouv.fr/v1",
        description="Albert API base URL",
    )
    api_key: str = Field(
        default="",
        description="Albert API key",
        json_schema_extra={"widget": "password"},
    )
    temperature: float = Field(
        default=0.7,
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

    def __init__(self, **data):
        super().__init__(**data)
        if not self.api_key:
            self.api_key = _load_api_key()

    def save(self):
        if self.api_key:
            _save_api_key(self.api_key)
        # Don't persist the key to YAML — keep it in keyring only
        saved_key = self.api_key
        self.api_key = ""
        super().save()
        self.api_key = saved_key

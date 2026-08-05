"""Kimi backend settings — API key stored in the system keyring."""
from pydantic import Field
from SciQLop.components.settings import SettingsCategory
from SciQLop.components.settings.backend import ConfigEntry

_KEYRING_SERVICE = "sciqlop_kimi"
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


class KimiSettings(ConfigEntry):
    category = SettingsCategory.PLUGINS
    subcategory = "Kimi"

    api_key: str = Field(
        default="",
        description="Moonshot API key (overrides the Kimi CLI config when set)",
        json_schema_extra={"widget": "password"},
    )
    base_url: str = Field(
        default="https://api.moonshot.ai/v1",
        description="Moonshot API base URL",
    )
    model: str = Field(
        default="kimi-k2-thinking-turbo",
        description="Model to use when the API key above is set",
    )
    max_context_size: int = Field(
        default=262144,
        description="Model context window in tokens",
        gt=0,
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

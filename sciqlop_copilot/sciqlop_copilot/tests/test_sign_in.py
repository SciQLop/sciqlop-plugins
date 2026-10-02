"""The dock re-activates the backend on every re-bind (each agent plugin's load() does one),
and each activation asked for a sign-in: users went through the GitHub device flow again
and again."""
import sys
from types import SimpleNamespace

import pytest

import sciqlop_copilot
from sciqlop_copilot import settings


@pytest.fixture
def keyring(monkeypatch):
    store = {}
    fake = SimpleNamespace(
        get_password=lambda service, user: store.get((service, user)),
        set_password=lambda service, user, value: store.__setitem__((service, user), value),
        delete_password=lambda service, user: store.pop((service, user), None),
    )
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setattr(settings, "_session_token", "", raising=False)
    return fake


@pytest.fixture
def dialogs(monkeypatch):
    """Fake login dialog; `on_exec` runs while it is 'open', like Qt's nested event loop."""
    opened = []

    class FakeDialog:
        on_exec = staticmethod(lambda: None)

        def __init__(self, parent=None):
            opened.append(self)
            self.token = "gh-token"

        def exec(self):
            FakeDialog.on_exec()
            return sciqlop_copilot.QDialog.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(sciqlop_copilot, "_DeviceLoginDialog", FakeDialog)
    monkeypatch.setattr(sciqlop_copilot, "fetch_models", lambda: [])
    return SimpleNamespace(opened=opened, cls=FakeDialog)


def test_a_sign_in_requested_while_one_is_open_opens_no_second_dialog(keyring, dialogs):
    dialogs.cls.on_exec = staticmethod(lambda: sciqlop_copilot.run_sign_in_flow(None))

    assert sciqlop_copilot.run_sign_in_flow(None) is True

    assert len(dialogs.opened) == 1


def test_no_dialog_when_a_token_is_already_stored(keyring, dialogs):
    settings.save_github_token("already-signed-in")

    assert sciqlop_copilot.run_sign_in_flow(None) is True

    assert dialogs.opened == []


def test_a_token_the_keyring_refuses_is_kept_for_the_session(keyring, monkeypatch):
    def refuse(*args):
        raise RuntimeError("no Secret Service")

    monkeypatch.setattr(keyring, "set_password", refuse)

    settings.save_github_token("gh-token")

    assert settings.load_github_token() == "gh-token"

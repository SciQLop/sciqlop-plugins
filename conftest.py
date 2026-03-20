"""Root conftest: stub out Qt/SciQLop-only imports unavailable in test environment."""
import sys
from unittest.mock import MagicMock

_GUI_MODULES = [
    "PySide6QtAds",
    "PySide6",
    "PySide6.QtWidgets",
    "PySide6.QtCore",
    "PySide6.QtGui",
]

for _mod in _GUI_MODULES:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

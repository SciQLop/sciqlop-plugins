from pathlib import Path
import logging
import shutil

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolButton

from .moments_vp import register_moments_vps

log = logging.getLogger(__name__)


def speasy_archive_dir() -> Path:
    from speasy.data_providers.generic_archive import user_inventory_dir
    return Path(user_inventory_dir())


def install_inventory():
    source = Path(__file__).parent / "inventory.yaml"
    dest = speasy_archive_dir() / "msa_bepi.yaml"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def rebuild_speasy_inventory():
    from speasy.core.dataprovider import PROVIDERS
    if "archive" not in PROVIDERS:
        log.warning("Speasy's archive provider is disabled, MSA products will not be listed")
        return
    try:
        PROVIDERS["archive"].update_inventory()
        republish_archive_tree()
    except Exception:
        log.exception("Failed to publish the MSA products")


def republish_archive_tree():
    # simplify: SciQLop <=0.13 copies Speasy's inventory into its product tree once, when
    # speasy_provider loads, which is before this plugin adds its inventory. Rebuild the
    # whole `archive` node by hand; drop this once SciQLop refreshes the tree itself.
    import speasy as spz
    from SciQLopPlots import ProductsModel, ProductsModelNode
    from SciQLop.plugins.speasy_provider.speasy_provider import explore_nodes, DATA_ARCHIVE_DESCRIPTIONS

    if ProductsModel.node(["speasy"]) is None:
        return
    node = ProductsModelNode("archive", metadata={"description": DATA_ARCHIVE_DESCRIPTIONS["archive"]},
                             icon="archive")
    explore_nodes(spz.inventories.tree.archive, node, provider="Speasy")
    ProductsModel.instance().add_node(["speasy"], node)


def _find_central_area(main_window):
    """At load time welcome's area is not laid out yet, so addWidgetIntoDock(area=None)
    would open the dock in a new area above it; resolve the target ourselves."""
    biggest = getattr(main_window, "_find_biggest_area", lambda: None)()
    if biggest is not None:
        return biggest
    welcome = main_window.dock_manager.findDockWidget("Welcome")
    return welcome.dockAreaWidget() if welcome is not None else None


class MSAPlugin(QObject):
    def __init__(self, main_window):
        super().__init__(main_window)
        self._main_window = main_window
        self._setup_quicklook_menu()
        self._setup_fit_inspector()

    def _setup_quicklook_menu(self):
        from .quicklooks import TEMPLATES, create_quicklook

        self._menu = QMenu("MSA Quick-Looks", self._main_window)
        for template_name in TEMPLATES:
            action = QAction(template_name, self._menu)
            def _on_quicklook(checked, name=template_name):
                try:
                    create_quicklook(name)
                except Exception:
                    log.exception("Failed to create quick-look '%s'", name)
            action.triggered.connect(_on_quicklook)
            self._menu.addAction(action)

        self._quicklook_button = QToolButton(self._main_window)
        self._quicklook_button.setText("MSA Quick-Looks")
        self._quicklook_button.setMenu(self._menu)
        self._quicklook_button.setPopupMode(QToolButton.InstantPopup)
        self._main_window.toolBar.addWidget(self._quicklook_button)

    def _setup_fit_inspector(self):
        import PySide6QtAds as QtAds
        from .fit_inspector import FitInspector

        self._fit_inspector = FitInspector()
        self._main_window.addWidgetIntoDock(QtAds.DockWidgetArea.TopDockWidgetArea, self._fit_inspector,
                                            area=_find_central_area(self._main_window))
        dock_widget = self._main_window.dock_manager.findDockWidget(self._fit_inspector.windowTitle())
        if dock_widget is None:
            self._main_window.toolsMenu.addAction("MSA Fit Inspector", self._fit_inspector.show)
            return
        dock_widget.toggleView(False)
        # The QtAds toggle action keeps the dock tabbed with welcome; show() on the widget would not.
        self._main_window.toolsMenu.addAction(dock_widget.toggleViewAction())
        self._menu.addSeparator()
        self._menu.addAction(dock_widget.toggleViewAction())

    async def close(self):
        pass


def load(main_window):
    install_inventory()
    rebuild_speasy_inventory()
    register_moments_vps()
    return MSAPlugin(main_window)

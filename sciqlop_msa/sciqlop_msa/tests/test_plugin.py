import logging
import sys
from types import ModuleType, SimpleNamespace

import pytest
import speasy as spz
from speasy.core import dataprovider

from sciqlop_msa import plugin


@pytest.fixture
def products_model(monkeypatch):
    """Fake SciQLop product tree holding a `speasy` root, as speasy_provider leaves it."""
    added, explored = [], []
    model = SimpleNamespace(add_node=lambda path, node: added.append((path, node)))
    plots = ModuleType("SciQLopPlots")
    plots.ProductsModel = SimpleNamespace(
        instance=lambda: model,
        node=lambda path: object() if path == ["speasy"] else None,
    )
    plots.ProductsModelNode = lambda name, metadata, icon: SimpleNamespace(name=name, icon=icon)
    speasy_provider = ModuleType("SciQLop.plugins.speasy_provider.speasy_provider")
    speasy_provider.explore_nodes = lambda inventory, node, provider: explored.append((inventory, node))
    speasy_provider.DATA_ARCHIVE_DESCRIPTIONS = {"archive": "Local archive files"}
    monkeypatch.setitem(sys.modules, "SciQLopPlots", plots)
    monkeypatch.setitem(sys.modules, "SciQLop.plugins.speasy_provider.speasy_provider", speasy_provider)
    return SimpleNamespace(added=added, explored=explored)


def test_archive_node_is_republished_after_inventory_update(monkeypatch, products_model):
    updates = []
    archive_inventory = object()
    monkeypatch.setitem(dataprovider.PROVIDERS, "archive",
                        SimpleNamespace(update_inventory=lambda: updates.append(True)))
    monkeypatch.setattr(spz.inventories.tree, "archive", archive_inventory, raising=False)

    plugin.rebuild_speasy_inventory()

    assert updates == [True]
    assert [(path, node.name) for path, node in products_model.added] == [(["speasy"], "archive")]
    assert products_model.explored[0][0] is archive_inventory


def test_disabled_archive_provider_is_reported(monkeypatch, products_model, caplog):
    monkeypatch.delitem(dataprovider.PROVIDERS, "archive", raising=False)

    with caplog.at_level(logging.WARNING):
        plugin.rebuild_speasy_inventory()

    assert products_model.added == []
    assert "archive provider" in caplog.text

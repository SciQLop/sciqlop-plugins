import sys
from types import ModuleType, SimpleNamespace

import pytest

from sciqlop_msa import quicklooks
from sciqlop_msa.moments_fit import MODEL_CHOICES


def test_variant_template_puts_one_moment_per_plot_and_every_model_in_it():
    plots = quicklooks.model_variant_plots("alphas")

    assert [p.plot for p in plots] == [m for m in range(3) for _ in MODEL_CHOICES]
    assert {p.path for p in plots if p.plot == 1} == {"msa/moments_fit/alphas/T_c"}
    assert [p.label for p in plots if p.plot == 0] == list(MODEL_CHOICES)
    assert all(p.inputs == {"model": model, "floor": "legacy"}
               for p, model in zip(plots, list(MODEL_CHOICES.values()) * 3))


def test_there_is_one_variant_template_per_species():
    names = [n for n in quicklooks.TEMPLATES if "all models" in n]

    assert len(names) == 4 and any("H⁺" in n for n in names)


@pytest.fixture
def fake_plot_api(monkeypatch):
    calls, graphs = [], []

    class FakeGraphImpl:
        """Like SciQLopLineGraphFunction: no line, so no label, until data arrives."""

        def __init__(self):
            self.lines, self._labels, self._slots = 0, [], []
            self.data_changed = SimpleNamespace(connect=self._slots.append)

        def line_count(self):
            return self.lines

        def labels(self):
            return self._labels

        def set_labels(self, labels):
            if len(labels) != self.lines:
                raise RuntimeError("Invalid number of labels")
            self._labels = labels

        def receive_data(self):
            self.lines, self._labels = 1, ["T_c"]
            for slot in self._slots:
                slot()

    class Graph:
        def __init__(self):
            self._impl = FakeGraphImpl()

    class Panel:
        time_range = None
        plots = 0

        def plot_product(self, path, plot_index=-1, product_inputs=None):
            if plot_index == -1:
                Panel.plots += 1
            calls.append((path, plot_index, product_inputs))
            graphs.append(Graph())
            return SimpleNamespace(), graphs[-1]

    plot = ModuleType("SciQLop.user_api.plot")
    plot.create_plot_panel = Panel
    plot.TimeRange = lambda a, b: (a, b)
    monkeypatch.setitem(sys.modules, "SciQLop.user_api.plot", plot)
    return SimpleNamespace(calls=calls, graphs=graphs, panel_cls=Panel)


def test_creating_a_variant_template_draws_each_variant_into_its_plot_with_its_label(fake_plot_api):
    quicklooks.create_quicklook("Ground Moments, all models — H⁺")

    calls = fake_plot_api.calls
    assert len(calls) == 3 * len(MODEL_CHOICES)
    assert [c[1] for c in calls[:len(MODEL_CHOICES)]] == [-1] + [0] * (len(MODEL_CHOICES) - 1)
    assert fake_plot_api.panel_cls.plots == 3
    assert calls[1][2] == {"model": "max", "floor": "legacy"}
    for graph in fake_plot_api.graphs:
        graph._impl.receive_data()
    assert [g._impl.labels() for g in fake_plot_api.graphs[:2]] == [["Auto (best χ²)"], ["Maxwellian"]]

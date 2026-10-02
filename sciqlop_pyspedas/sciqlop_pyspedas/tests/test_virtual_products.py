import inspect
import typing

import cloudpickle

from sciqlop_pyspedas import virtual_products as vp
from sciqlop_pyspedas.catalog import SOURCES


def _fpi_ions():
    return next(s for s in SOURCES if s.label == "FPI ions")


def _hpca_h():
    return next(s for s in SOURCES if s.label == "HPCA H+")


def test_registers_eighteen_spectrograms():
    calls = []
    registered = vp.register_all(vp_factory=lambda path, cb, **kw: calls.append((path, kw)) or path)
    assert len(registered) == 18
    path, kw = calls[0]
    assert path.startswith("pyspedas/MMS/")
    assert kw["metadata"]["DISPLAY_TYPE"] == "spectrogram"


def test_one_bad_product_does_not_block_the_others():
    def factory(path, cb, **kw):
        if path.endswith("FPI ions/energy"):
            raise RuntimeError("boom")
        return path

    assert len(vp.register_all(vp_factory=factory)) == 17


def test_fpi_knobs():
    hints = typing.get_type_hints(vp.build_callback(_fpi_ions(), "energy"))
    assert typing.get_args(hints["probe"]) == ("1", "2", "3", "4")
    assert typing.get_args(hints["data_rate"]) == ("fast", "brst")


def test_hpca_knobs_default_to_srvy():
    cb = vp.build_callback(_hpca_h(), "pa")
    assert typing.get_args(typing.get_type_hints(cb)["data_rate"]) == ("srvy", "brst")
    assert inspect.signature(cb).parameters["data_rate"].default == "srvy"


def test_callback_forwards_to_worker(monkeypatch):
    seen = {}
    monkeypatch.setattr(vp, "worker_callback", lambda start, stop, **kw: seen.update(kw) or "ok")
    assert vp.build_callback(_fpi_ions(), "gyro")(1.0, 2.0, probe="3", data_rate="brst") == "ok"
    assert seen == dict(source=_fpi_ions(), output="gyro", probe="3", data_rate="brst")


def test_callback_survives_cloudpickle():
    # Same in-process round-trip SciQLop does to ship callbacks to its worker.
    cb = cloudpickle.loads(cloudpickle.dumps(vp.build_callback(_fpi_ions(), "energy")))
    assert list(inspect.signature(cb).parameters) == ["start", "stop", "probe", "data_rate"]


def test_callback_module_groups_into_plugin_worker():
    assert vp.build_callback(_fpi_ions(), "energy").__module__.split(".")[0] == "sciqlop_pyspedas"


def test_hint_spec_log_energy_linear_angles():
    assert vp.hint_spec("energy")["y2"]["scale"] == "log"
    assert vp.hint_spec("pa")["y2"]["scale"] == "linear"
    assert vp.hint_spec("pa")["z"]["scale"] == "log"


def test_load_registers_once(monkeypatch):
    import sciqlop_pyspedas

    calls = []
    monkeypatch.setattr(vp, "register_all", lambda: calls.append(1) or {"p": object()})
    monkeypatch.setattr(sciqlop_pyspedas, "_REGISTERED", {})
    sciqlop_pyspedas.load(object())
    sciqlop_pyspedas.load(object())
    assert calls == [1]

"""Exports: the file structure as YAML, plotted data as CSV / .npy, a subset of variables."""
import numpy as np
import pycdfpp
import pytest
import yaml

from cdf_workbench.document import from_cdf
from cdf_workbench.export import skeleton, skeleton_yaml

T = pycdfpp.DataType


@pytest.fixture
def cdf():
    cdf = pycdfpp.CDF()
    cdf.add_attribute("Project", ["ISTP", "SPDF"])
    cdf.add_attribute("Mixed", [np.arange(2, dtype=np.int32), [1.5]], [T.CDF_INT4, T.CDF_DOUBLE])
    cdf.add_variable("Epoch", values=np.array(["2020-01-01"], dtype="datetime64[ns]"), data_type=T.CDF_EPOCH)
    cdf["Epoch"].add_attribute("VALIDMIN", [np.datetime64("1996-01-01", "ns")], T.CDF_EPOCH)
    cdf.add_variable("B", values=np.ones((1, 3), dtype=np.float32),
                     compression=pycdfpp.CompressionType.gzip_compression)
    cdf["B"].add_attribute("FILLVAL", [np.float32(-1e31)], T.CDF_FLOAT)
    cdf["B"].add_attribute("UNITS", "nT")
    return pycdfpp.load(bytes(pycdfpp.save(cdf)))


def _plain(d):
    return yaml.safe_load(yaml.safe_dump(d))


def test_skeleton_matches_pycdfpp_without_reading_values(cdf):
    reference = pycdfpp.to_dict_skeleton(cdf)
    reference.pop("compression")
    for var in reference["variables"].values():
        var["shape"] = list(var["shape"])
    lazy = pycdfpp.load(bytes(pycdfpp.save(cdf)))

    ours = skeleton(from_cdf(lazy))

    assert _plain(ours) == _plain(reference)
    assert not any(v.values_loaded for _, v in lazy.items())


def test_skeleton_yaml_reads_back(cdf):
    loaded = yaml.safe_load(skeleton_yaml(from_cdf(cdf)))
    assert loaded["variables"]["B"]["attributes"]["UNITS"] == {"types": ["DataType.CDF_CHAR"], "values": ["nT"]}
    assert loaded["attributes"]["Project"]["values"] == ["ISTP", "SPDF"]


def _bundle(values, x, depend_1=None, labels=None, is_time_axis=True, display_type="line"):
    from SciQLop.core.plot_hints import PlotHints
    from cdf_workbench.file_view import PlotBundle
    return PlotBundle(x=np.asarray(x, dtype=np.float64), values=np.asarray(values, dtype=np.float64),
                      depend_1=None if depend_1 is None else np.asarray(depend_1, dtype=np.float64),
                      hints=PlotHints(display_type=display_type, component_labels=labels or []),
                      is_time_axis=is_time_axis)


def test_csv_has_iso_times_and_one_column_per_component(tmp_path):
    from cdf_workbench.export import write_csv
    path = tmp_path / "b.csv"
    write_csv(str(path), _bundle([[1.0, 2.0], [3.0, np.nan]], [0.0, 1.5], labels=["Bx", "By"]))

    lines = path.read_text().splitlines()
    assert lines[0] == "time,Bx,By"
    assert lines[1] == "1970-01-01T00:00:00.000000,1.0,2.0"
    assert lines[2] == "1970-01-01T00:00:01.500000,3.0,"


def test_csv_of_a_spectrogram_names_columns_after_the_bins(tmp_path):
    from cdf_workbench.export import write_csv
    path = tmp_path / "s.csv"
    write_csv(str(path), _bundle([[1.0, 2.0]], [5.0], depend_1=[10.0, 100.0], is_time_axis=False,
                                 display_type="spectrogram"))
    assert path.read_text().splitlines() == ["x,10,100", "5.0,1.0,2.0"]


def test_npz_keeps_axes(tmp_path):
    from cdf_workbench.export import write_npz
    path = tmp_path / "s.npz"
    write_npz(str(path), _bundle([[1.0, 2.0]], [5.0], depend_1=[10.0, 100.0], display_type="spectrogram"))
    data = np.load(path)
    assert list(data["values"][0]) == [1.0, 2.0] and list(data["depend_1"]) == [10.0, 100.0]
    assert data["time"][0] == np.datetime64("1970-01-01T00:00:05", "ns")


def test_subset_pulls_in_what_the_variables_point_at():
    from cdf_workbench.export import subset
    cdf = pycdfpp.CDF()
    for name in ("Epoch", "energy", "energy_delta", "labels", "flux", "other"):
        cdf.add_variable(name, values=np.ones(2))
    cdf["flux"].add_attribute("DEPEND_0", "Epoch")
    cdf["flux"].add_attribute("DEPEND_1", "energy")
    cdf["energy"].add_attribute("DELTA_PLUS_VAR", "energy_delta")
    cdf["flux"].add_attribute("LABL_PTR_1", "labels")
    cdf["flux"].add_attribute("CATDESC", "other")

    kept = subset(from_cdf(cdf), ["flux"])

    assert list(kept.keys()) == ["Epoch", "energy", "energy_delta", "labels", "flux"]


def test_csv_times_have_no_float_noise(tmp_path):
    from cdf_workbench.export import write_csv
    path = tmp_path / "t.csv"
    t = (np.datetime64("2020-07-05T04:00:00.123456", "us") - np.datetime64(0, "us")) / np.timedelta64(1, "s")
    write_csv(str(path), _bundle([1.0], [t]))
    assert path.read_text().splitlines()[1] == "2020-07-05T04:00:00.123456,1.0"

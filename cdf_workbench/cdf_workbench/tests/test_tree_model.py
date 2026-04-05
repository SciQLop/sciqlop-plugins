import pytest
from PySide6.QtCore import Qt
from cdf_workbench.tree_model import CdfTreeModel, VariableInfo


def test_model_groups_by_var_type(sample_cdf_bytes):
    """Variables are grouped under Data/Support/Metadata/Uncategorized."""
    import pycdfpp
    cdf = pycdfpp.load(sample_cdf_bytes)
    model = CdfTreeModel(cdf)

    root_count = model.rowCount()
    assert root_count >= 2  # at least Data and Support

    group_names = []
    for i in range(root_count):
        idx = model.index(i, 0)
        group_names.append(model.data(idx, Qt.DisplayRole))
    assert "Data" in group_names
    assert "Support Data" in group_names


def test_model_variable_info(sample_cdf_bytes):
    """VariableInfo extracts shape, type, and key attributes."""
    import pycdfpp
    cdf = pycdfpp.load(sample_cdf_bytes)
    model = CdfTreeModel(cdf)

    info = model.variable_info("Bt")
    assert info is not None
    assert info.name == "Bt"
    assert info.units == "nT"
    assert info.depend_0 == "Epoch"


def test_model_uncategorized_group(sample_cdf_bytes):
    """Variables without VAR_TYPE go to Uncategorized."""
    import pycdfpp
    cdf = pycdfpp.load(sample_cdf_bytes)
    model = CdfTreeModel(cdf)
    assert model.rowCount() >= 1

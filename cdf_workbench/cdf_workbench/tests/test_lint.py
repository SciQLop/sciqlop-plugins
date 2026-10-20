"""Lint runs lint.py as its own process: it must not need the plugin to be importable
(SciQLop loads plugins by file path, and Python 3.14's forkserver child couldn't import it)."""
import subprocess
import sys

import numpy as np
import pycdfpp
import pytest

from cdf_workbench import lint
from cdf_workbench.lint import LintIssue, LintReport, report_from_json, report_to_json


def test_report_json_round_trip():
    report = LintReport([LintIssue("ERROR", "missing FILLVAL", "ISTP-1", "B"), LintIssue("INFO", "x", "r", "")])
    assert report_from_json(report_to_json(report)) == report
    assert report_from_json(report_to_json(None)) is None


@pytest.fixture
def cdf_path(tmp_path):
    cdf = pycdfpp.CDF()
    cdf.add_variable("B", values=np.ones(3))
    path = tmp_path / "f.cdf"
    pycdfpp.save(cdf, str(path))
    return path


@pytest.mark.parametrize("from_stdin", [False, True])
def test_lint_child_runs_without_the_plugin_on_sys_path(cdf_path, tmp_path, from_stdin):
    args = [sys.executable, "-I", lint.__file__, "-" if from_stdin else str(cdf_path)]
    result = subprocess.run(args, input=cdf_path.read_bytes() if from_stdin else None,
                            capture_output=True, cwd=tmp_path, timeout=60)
    assert result.returncode == 0, result.stderr.decode()[-1000:]
    report_from_json(result.stdout.decode())

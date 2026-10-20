"""AstraLint ISTP conformance checking — pure module, no Qt dependency.

Also run as a script by the workbench: `python -I lint.py <path | ->` lints a file, or CDF bytes
from stdin, and prints the report as JSON. It imports nothing from the plugin, so it works even
though SciQLop loads plugins by file path. Keep it that way.
"""
from __future__ import annotations
import json
import sys
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass(frozen=True)
class LintIssue:
    severity: str  # ERROR, WARNING, INFO
    message: str
    rule: str
    target: str  # variable name or "" for file-level


@dataclass
class LintReport:
    issues: list[LintIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "ERROR")

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == "WARNING")

    def issues_for_variable(self, var_name: str) -> list[LintIssue]:
        return [i for i in self.issues if i.target == var_name]

    def file_level_issues(self) -> list[LintIssue]:
        return [i for i in self.issues if not i.target]


def run_lint(source: str | bytes) -> LintReport | None:
    """Run AstraLint ISTP suite on a CDF file. Returns None if astralint is unavailable."""
    try:
        from astralint.codecs import CdfCodec
        from astralint.astralint import get_suite
    except ImportError:
        return None

    file_model = CdfCodec.load(source)
    if file_model is None:
        return None

    suite = get_suite("ISTP")
    if suite is None:
        return None

    var_names = set(file_model.variables.keys())
    result_group = suite.run(file_model)
    return _collect_issues(result_group, var_names)


def _collect_issues(group, var_names: set[str]) -> LintReport:
    issues: list[LintIssue] = []
    _walk(group, var_names, issues)
    return LintReport(issues=issues)


def _walk(group, var_names: set[str], issues: list[LintIssue]) -> None:
    for result in group.results:
        if hasattr(result, "results"):
            _walk(result, var_names, issues)
        elif not result.valid:
            target = result.target if result.target in var_names else ""
            issues.append(LintIssue(
                severity=result.severity.value,
                message=result.message,
                rule=result.reference,
                target=target,
            ))


def report_to_json(report: Optional[LintReport]) -> str:
    return json.dumps(None if report is None else [asdict(i) for i in report.issues])


def report_from_json(text: str) -> Optional[LintReport]:
    issues = json.loads(text)
    return None if issues is None else LintReport([LintIssue(**i) for i in issues])


def _main(argv: list[str]) -> None:
    source = sys.stdin.buffer.read() if argv[1] == "-" else argv[1]
    print(report_to_json(run_lint(source)))


if __name__ == "__main__":
    _main(sys.argv)

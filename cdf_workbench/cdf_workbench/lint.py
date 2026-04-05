"""AstraLint ISTP conformance checking — pure module, no Qt dependency."""
from __future__ import annotations
from dataclasses import dataclass, field


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

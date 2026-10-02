"""Which plugins the compatibility smoke should run, as a GitHub Actions matrix.

A push smokes the plugins whose folder it touched; a change to the smoke
itself, a scheduled or manual run, or a push with no history to diff against
smokes them all.

Usage in CI: python smoke_plugins.py <event> <before-sha> <sha>  >> $GITHUB_OUTPUT
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SMOKE_FILES = (".github/workflows/compat.yml", ".github/scripts/smoke_plugins.py")


def all_plugins(repo: Path = REPO) -> list:
    return sorted(p.parent.parent.name for p in repo.glob("*/*/plugin.json") if p.parent.name == p.parent.parent.name)


def pick(event: str, changed: "list | None", plugins: list) -> list:
    if event != "push" or changed is None or any(f in SMOKE_FILES for f in changed):
        return list(plugins)
    touched = {f.split("/", 1)[0] for f in changed}
    return [p for p in plugins if p in touched]


def changed_files(before: str, sha: str) -> "list | None":
    if not before or set(before) == {"0"}:  # first push of a branch: nothing to diff against
        return None
    try:
        out = subprocess.run(["git", "diff", "--name-only", before, sha], cwd=REPO,
                             capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:  # before-sha unknown, e.g. after a force push
        return None
    return out.split()


if __name__ == "__main__":
    event, before, sha = sys.argv[1:4]
    print("plugins=" + json.dumps(pick(event, changed_files(before, sha), all_plugins())))

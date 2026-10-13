"""Best free model goes first in the dropdown, ranked from `opencode models --verbose`."""
import json
import subprocess


def _meta(cost=0, toolcall=True, reasoning=True, release="2026-01-01", context=128000, status="active", image=True):
    return {
        "status": status,
        "cost": {"input": cost, "output": cost, "cache": {"read": 0, "write": 0}},
        "limit": {"context": context, "output": 32000},
        "capabilities": {
            "toolcall": toolcall,
            "reasoning": reasoning,
            "input": {"text": True, "image": image},
        },
        "release_date": release,
    }


def _verbose(models):
    return "".join(f"{key}\n{json.dumps(meta, indent=2)}\n" for key, meta in models.items())


def test_parse_verbose_models_keys_each_json_block_by_its_header_line():
    from sciqlop_opencode import backend as bk

    text = _verbose({"opencode/a-free": _meta(), "opencode-go/b": _meta(cost=1)})
    parsed = bk.parse_verbose_models(text)
    assert set(parsed) == {"opencode/a-free", "opencode-go/b"}
    assert parsed["opencode-go/b"]["cost"]["input"] == 1


def test_parse_verbose_models_tolerates_garbage():
    from sciqlop_opencode import backend as bk

    assert bk.parse_verbose_models("") == {}
    assert bk.parse_verbose_models("warning: something\nopencode/x\n{broken") == {}


def test_best_free_model_ignores_paid_toolless_and_deprecated_models():
    from sciqlop_opencode import backend as bk

    metadata = {
        "paid": _meta(cost=3, release="2026-09-01"),
        "no-tools": _meta(toolcall=False, release="2026-09-01"),
        "old": _meta(status="deprecated", release="2026-09-01"),
        "ok": _meta(release="2025-01-01"),
    }
    assert bk.best_free_model(metadata) == "ok"


def test_best_free_model_requires_image_input():
    # The agent inspects plot screenshots; a text-only model can't see them.
    from sciqlop_opencode import backend as bk

    assert bk.best_free_model({
        "text-only-newest": _meta(image=False, release="2026-10-01"),
        "sees-images": _meta(release="2025-01-01"),
    }) == "sees-images"
    assert bk.best_free_model({"text-only": _meta(image=False)}) is None


def test_best_free_model_prefers_reasoning_then_newest_then_largest_context():
    from sciqlop_opencode import backend as bk

    assert bk.best_free_model({
        "new-plain": _meta(reasoning=False, release="2026-09-01"),
        "old-reasoning": _meta(release="2025-01-01"),
    }) == "old-reasoning"
    assert bk.best_free_model({
        "older": _meta(release="2026-01-01", context=1_000_000),
        "newer": _meta(release="2026-06-01"),
    }) == "newer"
    assert bk.best_free_model({
        "small": _meta(context=64000),
        "big": _meta(context=256000),
    }) == "big"


def test_best_free_model_is_none_without_free_candidates():
    from sciqlop_opencode import backend as bk

    assert bk.best_free_model({}) is None
    assert bk.best_free_model({"paid": _meta(cost=1)}) is None


def test_best_free_model_survives_missing_fields():
    from sciqlop_opencode import backend as bk

    assert bk.best_free_model({"bare": {"cost": {"input": 0, "output": 0}}}) is None
    assert bk.best_free_model({"no-date": {**_meta(), "release_date": None}}) == "no-date"


def test_fetch_models_puts_the_best_free_model_first(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(bk, "acp_config_options", lambda _cmd: {"model": [
        ("Go/GLM", "opencode-go/glm-5.2"),
        ("Zen/Old Free", "opencode/old-free"),
        ("Zen/New Free", "opencode/new-free"),
    ]})
    monkeypatch.setattr(bk, "model_metadata", lambda _exe: {
        "opencode-go/glm-5.2": _meta(cost=2, release="2026-10-01"),
        "opencode/old-free": _meta(release="2025-06-01"),
        "opencode/new-free": _meta(release="2026-08-01"),
    })
    assert bk.fetch_models() == [
        ("Zen/New Free", "opencode/new-free"),
        ("Default (opencode)", None),
        ("Go/GLM", "opencode-go/glm-5.2"),
        ("Zen/Old Free", "opencode/old-free"),
    ]


def test_fetch_models_never_promotes_a_model_acp_did_not_offer(monkeypatch):
    # ACP lists only models of authenticated providers; set_config_option
    # rejects anything else, so a free model unknown to ACP must not appear.
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(bk, "acp_config_options", lambda _cmd: {"model": [("Go/GLM", "opencode-go/glm-5.2")]})
    monkeypatch.setattr(bk, "model_metadata", lambda _exe: {"opencode/free": _meta()})
    assert bk.fetch_models() == [("Default (opencode)", None), ("Go/GLM", "opencode-go/glm-5.2")]


def test_model_metadata_degrades_to_empty_on_cli_failure(monkeypatch):
    from sciqlop_opencode import backend as bk

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired("opencode", 1)

    monkeypatch.setattr(bk.subprocess, "run", boom)
    assert bk.model_metadata("/usr/bin/opencode") == {}


def test_model_metadata_runs_the_verbose_listing(monkeypatch):
    from sciqlop_opencode import backend as bk

    seen = []

    def fake_run(cmd, **_kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=_verbose({"opencode/x": _meta()}), stderr="")

    monkeypatch.setattr(bk.subprocess, "run", fake_run)
    assert set(bk.model_metadata("/usr/bin/opencode")) == {"opencode/x"}
    assert seen == [["/usr/bin/opencode", "models", "--verbose"]]

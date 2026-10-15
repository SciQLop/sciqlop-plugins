"""Best free model goes first in the dropdown, ranked from v2's `model.list` API."""
import json
import subprocess


def _meta(cost=0, tools=True, reasoning=True, release=1767225600000, context=128000, status="active", image=True):
    """One entry of `opencode api --standalone model.list` (opencode 2.x schema)."""
    return {
        "status": status,
        "cost": [{"input": cost, "output": cost, "cache": {"read": 0, "write": 0}}],
        "limit": {"context": context, "output": 32000},
        "capabilities": {
            "tools": tools,
            "input": ["text", "image"] if image else ["text"],
            "output": ["text"],
        },
        "variants": [{"id": "high", "settings": {"reasoningEffort": "high"}}] if reasoning else [],
        "time": {"released": release},
    }


def _listing(models):
    """Serialize `{provider/id: meta}` the way `model.list` prints it."""
    data = []
    for key, meta in models.items():
        provider, _, model_id = key.partition("/")
        data.append({"id": model_id, "modelID": model_id, "providerID": provider, **meta})
    return json.dumps({"location": {"directory": "/tmp"}, "data": data})


def test_parse_model_list_keys_each_model_by_provider_and_id():
    from sciqlop_opencode import backend as bk

    parsed = bk.parse_model_list(_listing({"opencode/a-free": _meta(), "opencode-go/b": _meta(cost=1)}))
    assert set(parsed) == {"opencode/a-free", "opencode-go/b"}
    assert parsed["opencode-go/b"]["cost"][0]["input"] == 1


def test_parse_model_list_tolerates_garbage():
    from sciqlop_opencode import backend as bk

    assert bk.parse_model_list("") == {}
    assert bk.parse_model_list("UnknownError: boom") == {}
    assert bk.parse_model_list('{"data": "nope"}') == {}
    assert bk.parse_model_list('{"data": [{"id": "x"}]}') == {}


def test_best_free_model_ignores_paid_toolless_and_deprecated_models():
    from sciqlop_opencode import backend as bk

    metadata = {
        "paid": _meta(cost=3, release=1788220800000),
        "no-tools": _meta(tools=False, release=1788220800000),
        "old": _meta(status="deprecated", release=1788220800000),
        "ok": _meta(release=1735689600000),
    }
    assert bk.best_free_model(metadata) == "ok"


def test_best_free_model_requires_image_input():
    # The agent inspects plot screenshots; a text-only model can't see them.
    from sciqlop_opencode import backend as bk

    assert bk.best_free_model({
        "text-only-newest": _meta(image=False, release=1790812800000),
        "sees-images": _meta(release=1735689600000),
    }) == "sees-images"
    assert bk.best_free_model({"text-only": _meta(image=False)}) is None


def test_best_free_model_prefers_reasoning_then_newest_then_largest_context():
    from sciqlop_opencode import backend as bk

    assert bk.best_free_model({
        "new-plain": _meta(reasoning=False, release=1788220800000),
        "old-reasoning": _meta(release=1735689600000),
    }) == "old-reasoning"
    assert bk.best_free_model({
        "older": _meta(release=1767225600000, context=1_000_000),
        "newer": _meta(release=1780272000000),
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

    assert bk.best_free_model({"bare": {"cost": [{"input": 0, "output": 0}]}}) is None
    assert bk.best_free_model({"no-cost": {**_meta(), "cost": []}}) is None
    assert bk.best_free_model({"no-date": {**_meta(), "time": None}}) == "no-date"


def test_fetch_models_puts_the_best_free_model_first(monkeypatch):
    from sciqlop_opencode import backend as bk

    monkeypatch.setattr(bk, "resolve_opencode_executable", lambda: "/usr/bin/opencode")
    monkeypatch.setattr(bk, "acp_config_options", lambda _cmd: {"model": [
        ("Go/GLM", "opencode-go/glm-5.2"),
        ("Zen/Old Free", "opencode/old-free"),
        ("Zen/New Free", "opencode/new-free"),
    ]})
    monkeypatch.setattr(bk, "model_metadata", lambda _exe: {
        "opencode-go/glm-5.2": _meta(cost=2, release=1790812800000),
        "opencode/old-free": _meta(release=1748736000000),
        "opencode/new-free": _meta(release=1785542400000),
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


def test_model_metadata_queries_a_private_server(monkeypatch):
    # --standalone: without it the CLI starts opencode's persistent background
    # service, which would outlive SciQLop.
    from sciqlop_opencode import backend as bk

    seen = []

    def fake_run(cmd, **_kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=_listing({"opencode/x": _meta()}), stderr="")

    monkeypatch.setattr(bk.subprocess, "run", fake_run)
    assert set(bk.model_metadata("/usr/bin/opencode")) == {"opencode/x"}
    assert seen == [["/usr/bin/opencode", "api", "--standalone", "model.list"]]

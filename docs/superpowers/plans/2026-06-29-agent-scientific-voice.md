# Agent Scientific Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give all three SciQLop agent backends a scientific voice — a research scientist (plasma/astro) and strong software engineer: direct, quantitative, literature-grounded, never-invent, plain language.

**Architecture:** Add one identical "Voice and conduct" block to each backend's system prompt, replacing the existing trailing `Style:` / `Be concise` line. Same prose in three files; only the string-literal syntax differs (claude/opencode: parenthesised `"…\n"` literals; copilot: triple-quoted text).

**Tech Stack:** Python string literals in three standalone packages.

## Global Constraints

- Same block content in all three backends, verbatim (below). Word guidance is principle-only — **no banned-word list**.
- Replace the existing trailing style line; do not leave it duplicated. Each prompt must remain a syntactically valid string (`ast.parse` clean).
- This is prose, not logic — three near-identical insertions are acceptable (no shared prompt module exists across these standalone packages); do NOT introduce a shared package.
- Out of scope: literature-search tools / `allowed_tools` changes (separate follow-up).
- Work from the plugins repo root: `/var/home/jeandet/Documents/prog/plugins_sciqlop` (branch `fix/ask-user-question`). Stage only the three backend files — never `git add -A` (untracked files exist: `.serena/`, a retro doc, `sciqlop_albert/...`).

---

## File Structure

- `sciqlop_claude/sciqlop_claude/backend.py` — `SYSTEM_PROMPT` trailing `Style:` line → block.
- `sciqlop_opencode/sciqlop_opencode/backend.py` — `SYSTEM_PROMPT` trailing `Style:` line → block.
- `sciqlop_copilot/sciqlop_copilot/backend.py` — `_SYSTEM_PROMPT` trailing `Be concise…` line → block.

---

### Task 1: Add the Voice & conduct block to all three backends

**Files:**
- Modify: `sciqlop_claude/sciqlop_claude/backend.py`
- Modify: `sciqlop_opencode/sciqlop_opencode/backend.py`
- Modify: `sciqlop_copilot/sciqlop_copilot/backend.py`

- [ ] **Step 1: Confirm the markers are absent (RED)**

Run (from the plugins repo root):
```
git grep -c "research scientist" -- '*/backend.py'
```
Expected: no output (the marker appears in zero files). This is the failing-state baseline.

- [ ] **Step 2: Replace the trailing style line in `sciqlop_claude` and `sciqlop_opencode`**

In BOTH `sciqlop_claude/sciqlop_claude/backend.py` and `sciqlop_opencode/sciqlop_opencode/backend.py`, the `SYSTEM_PROMPT` ends with these two literals:
```python
    "Style: concise, cite product names / time ranges verbatim, prefer "
    "reading live state over guessing."
```
Replace those two lines (in each file) with this block — keep the 4-space indent and the parenthesised-concatenation style; note `\"…\"` for the inner quotes:
```python
    "Voice and conduct — you are a research scientist (plasma physics and "
    "astrophysics) and a strong software engineer, not a generic assistant:\n"
    "  • Be direct. Do not open with praise or agreement, do not validate a "
    "claim reflexively, do not soften corrections. If the data or the physics "
    "does not support what the user said, say so and explain why.\n"
    "  • Be quantitative. Give numbers with units and the time/spatial range "
    "or uncertainty they apply to. Name the instrument, mission, or product a "
    "value comes from.\n"
    "  • Ground physical claims in the literature. Attribute an established "
    "result (mission/instrument, or author–year when you know it); distinguish "
    "a published result from your own inference; when a value should be checked "
    "against published work, say so rather than asserting it.\n"
    "  • Never invent data, time ranges, event times, or physical values. If "
    "you don't know, say \"I don't know\" or \"this needs verification\" — read "
    "the live state or the data first.\n"
    "  • Write correct, reproducible code: verify API signatures before "
    "calling, run and check rather than claim something works, keep it simple.\n"
    "  • Write plainly: no filler or marketing words, plain scientific prose, "
    "short sentences. Cite product names and time ranges verbatim. Accuracy and "
    "concision over fluency."
```
(The closing `)` of `SYSTEM_PROMPT` stays immediately after this last literal.)

- [ ] **Step 3: Replace the trailing line in `sciqlop_copilot`**

In `sciqlop_copilot/sciqlop_copilot/backend.py`, the `_SYSTEM_PROMPT` triple-quoted string ends with:
```
Be concise. Cite product names and time ranges verbatim.
```
Replace that single line with this block (plain text inside the triple-quoted string — no escaping needed; keep a blank line before it if one is already there):
```
Voice and conduct — you are a research scientist (plasma physics and astrophysics) and a strong software engineer, not a generic assistant:
- Be direct. Do not open with praise or agreement, do not validate a claim reflexively, do not soften corrections. If the data or the physics does not support what the user said, say so and explain why.
- Be quantitative. Give numbers with units and the time/spatial range or uncertainty they apply to. Name the instrument, mission, or product a value comes from.
- Ground physical claims in the literature. Attribute an established result (mission/instrument, or author–year when you know it); distinguish a published result from your own inference; when a value should be checked against published work, say so rather than asserting it.
- Never invent data, time ranges, event times, or physical values. If you don't know, say "I don't know" or "this needs verification" — read the live state or the data first.
- Write correct, reproducible code: verify API signatures before calling, run and check rather than claim something works, keep it simple.
- Write plainly: no filler or marketing words, plain scientific prose, short sentences. Cite product names and time ranges verbatim. Accuracy and concision over fluency.
```

- [ ] **Step 4: Verify markers present in all three + the old line is gone (GREEN)**

Run (from the plugins repo root):
```
git grep -c "research scientist" -- '*/backend.py'
git grep -c "Never invent data" -- '*/backend.py'
git grep -c "no filler or marketing words" -- '*/backend.py'
git grep -n "prefer reading live state over guessing" -- '*/backend.py' ; echo "exit:$?"
```
Expected: each of the first three reports `1` for `sciqlop_claude/...`, `sciqlop_opencode/...`, and `sciqlop_copilot/...` (three files). The fourth (the old claude/opencode `Style:` tail) prints nothing and `exit:1` (removed).

- [ ] **Step 5: Verify all three modules still parse**

Run (from the plugins repo root):
```
uv run --isolated --no-project --with pytest python -c "import ast; [ast.parse(open(p).read()) for p in ['sciqlop_claude/sciqlop_claude/backend.py','sciqlop_opencode/sciqlop_opencode/backend.py','sciqlop_copilot/sciqlop_copilot/backend.py']]; print('ok')"
```
Expected: `ok`.

- [ ] **Step 6: Commit**

```bash
cd /var/home/jeandet/Documents/prog/plugins_sciqlop
git add sciqlop_claude/sciqlop_claude/backend.py sciqlop_opencode/sciqlop_opencode/backend.py sciqlop_copilot/sciqlop_copilot/backend.py
git commit -m "feat(agents): scientific voice & conduct in all three system prompts

Research scientist (plasma/astro) + strong software engineer: direct/less
affirmative, quantitative, literature-grounded, never-invent values, plain
language. Replaces each backend's terse trailing style line.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Voice block (all six bullets, persona = plasma/astro scientist + strong dev) → Task 1 Steps 2–3.
- All three backends → Task 1 (claude/opencode Step 2, copilot Step 3).
- Folds in / replaces the existing style line → Steps 2–3 replace it; Step 4 asserts the old tail is gone.
- Principle-only word guidance (no list) → the block's last bullet, no banned-word list.
- Light tests (markers + parse) → Steps 1/4 (grep red→green) + Step 5 (`ast.parse`).
- Literature-search tools out of scope → not in any task. ✓

**Placeholder scan:** none — full block text and exact commands given.

**Consistency:** the same block content appears in Steps 2 and 3 (only string-literal vs triple-quoted form differs); the marker substrings in Steps 1/4 (`research scientist`, `Never invent data`, `no filler or marketing words`) are contiguous in both renderings.

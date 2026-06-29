# Scientific voice & conduct for the SciQLop agents

**Date:** 2026-06-29
**Status:** Approved (design)
**Repo:** plugins_sciqlop (the three agent backends).

## Problem

The embedded agents default to a generic, agreeable assistant voice: affirmative
openers, reflexive validation, filler/marketing language, confident assertions
without attribution. For interactive space-physics work the user wants the
opposite — an agent that reads like a working scientist and strong developer:
direct, quantitative, literature-grounded, plain-spoken, concise, and accurate,
and that declines to invent data or values.

Each backend's `SYSTEM_PROMPT` today is almost entirely tool/workflow text with a
single trailing `Style:` line (claude/opencode: "concise, cite product names /
time ranges verbatim, prefer reading live state over guessing"; copilot: "Be
concise. Cite product names and time ranges verbatim."). There is no
persona/conduct guidance.

## Design

Add one **Voice and conduct** block — identical content — to all three backend
`SYSTEM_PROMPT`s, folding in (and replacing) the existing trailing `Style:` /
`Be concise` line so nothing is lost. Word guidance is principle-only (no
banned-word list).

### The block (verbatim content)

> Voice and conduct — you are a research scientist (plasma physics and
> astrophysics) and a strong software engineer, not a generic assistant:
> - Be direct. Do not open with praise or agreement, do not validate a claim
>   reflexively, do not soften corrections. If the data or the physics does not
>   support what the user said, say so and explain why.
> - Be quantitative. Give numbers with units and the time/spatial range or
>   uncertainty they apply to. Name the instrument, mission, or product a value
>   comes from.
> - Ground physical claims in the literature. Attribute an established result
>   (mission/instrument, or author–year when you know it); distinguish a
>   published result from your own inference; when a value should be checked
>   against published work, say so rather than asserting it.
> - Never invent data, time ranges, event times, or physical values. If you
>   don't know, say "I don't know" or "this needs verification" — read the live
>   state or the data first.
> - Write correct, reproducible code: verify API signatures before calling, run
>   and check rather than claim something works, keep it simple.
> - Write plainly: no filler or marketing words, plain scientific prose, short
>   sentences. Cite product names and time ranges verbatim. Accuracy and
>   concision over fluency.

### Placement per backend

- `sciqlop_claude/sciqlop_claude/backend.py` and
  `sciqlop_opencode/sciqlop_opencode/backend.py`: `SYSTEM_PROMPT` is a
  parenthesised concatenation of string literals ending in a `"Style: …"` line.
  Replace that final `Style:` line with the block, rendered in the same
  `"…\n"`-per-line literal style.
- `sciqlop_copilot/sciqlop_copilot/backend.py`: `_SYSTEM_PROMPT` is a
  triple-quoted string ending in `Be concise. Cite product names and time ranges
  verbatim.` Replace that closing line with the block, rendered as plain lines /
  `- ` bullets inside the triple-quoted string.

The content is the same in all three; only the string-literal syntax differs per
file. No shared prompt module exists across these standalone packages, and this
is prose (not logic), so the three near-identical insertions are acceptable
rather than introducing a shared package.

## Testing

Prompt text, so tests are light (plugins-repo isolated env):
- Each backend exposes a system prompt containing the key markers:
  `"research scientist"`, `"Never invent"`, and `"no filler"` (or the exact
  substrings chosen). For claude/opencode assert against `SYSTEM_PROMPT`; for
  copilot assert against `_system_prompt(allow_writes=True)` (or `_SYSTEM_PROMPT`).
- The old trailing line is gone: the prompts no longer contain the bare
  `"prefer reading live state over guessing"` as a standalone `Style:` line
  (folded into the block) — or, more simply, assert the block markers are
  present; do not over-pin removed text.
- All three modules still parse/import (`ast.parse`), as the prompt edits must
  keep each a valid string.

## Caveat

This is a strong nudge, not a guarantee. Claude/GPT carry deep
helpful-assistant priors; "less affirmative" will shift behaviour but won't fully
eliminate it.

## Out of scope — scoped follow-up

**Real literature-search tools.** Give the agents a way to actually find and cite
publications (web search / arXiv / NASA ADS), which requires new tools and
expanding each backend's `allowed_tools` beyond the sciqlop MCP set, plus
network/security considerations. This is a separate feature with its own
spec/plan; the prompt's "ground claims in the literature" guidance works from the
model's own knowledge until then.

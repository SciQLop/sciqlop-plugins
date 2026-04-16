"""Albert backend — OpenAI-compatible chat completions with tool calling."""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

import httpx

from SciQLop.components.agents import BackendContext, SessionEntry
from SciQLop.components.agents.backend import StreamBlock
from SciQLop.components.agents.chat import (
    ChatMessage,
    ImageBlock,
    TextBlock,
    write_b64_image,
)

from .settings import AlbertSettings

_DEFAULT_BASE_URL = "https://albert.api.etalab.gouv.fr/v1"

_SYSTEM_BASE = (
    "You are a helper embedded inside SciQLop, a Qt desktop application for "
    "space-physics time-series visualization. You act on the live running "
    "instance through function calls.\n\n"
    "Read functions — call these freely, they never mutate state:\n"
    "  - sciqlop_window_state / sciqlop_list_panels / sciqlop_active_panel\n"
    "  - sciqlop_screenshot_panel / sciqlop_screenshot_plot\n"
    "  - sciqlop_api_reference — call BEFORE writing code against the user API\n"
    "  - sciqlop_products_tree — walk the live product tree; USE THIS to find "
    "    product paths before calling plot_product\n"
    "  - sciqlop_speasy_inventory — browse speasy uids (NOT for plot_product)\n"
    "  - sciqlop_wait_for_plot_data — call after plot_product, BEFORE screenshot\n"
    "  - sciqlop_list_notebooks / sciqlop_read_notebook\n\n"
)

_WRITES_ENABLED = (
    "Write functions — ENABLED, you may call these (the user will be prompted "
    "to approve each call):\n"
    "  - sciqlop_create_panel — returns the new panel name\n"
    "  - sciqlop_set_time_range(start, stop, name?)\n"
    "  - sciqlop_exec_python(code) — run Python inside SciQLop's IPython kernel\n"
    "  - sciqlop_create_notebook / sciqlop_write_notebook_cell / "
    "sciqlop_insert_notebook_cell / sciqlop_delete_notebook_cell\n\n"
    "Typical plot workflow:\n"
    "  1. sciqlop_products_tree('') -> drill to the target parameter path.\n"
    "  2. sciqlop_create_panel() -> capture the returned panel name.\n"
    "  3. sciqlop_exec_python: "
    "plot_panel('<name>').plot_product('<path>', plot_type=PlotType.TimeSeries)\n"
    "  4. sciqlop_set_time_range if needed.\n"
    "  5. sciqlop_wait_for_plot_data.\n"
    "  6. sciqlop_screenshot_panel.\n\n"
)

_WRITES_DISABLED = (
    "Write functions are DISABLED. Do NOT call sciqlop_create_panel, "
    "sciqlop_set_time_range, sciqlop_exec_python, or notebook-editing tools — "
    "they will be rejected. If the user asks you to modify something, tell "
    "them to enable 'Allow write actions' first.\n\n"
)

_SYSTEM_TAIL = "Be concise. Cite product names and time ranges verbatim."


def _system_prompt(allow_writes: bool) -> str:
    return _SYSTEM_BASE + (_WRITES_ENABLED if allow_writes else _WRITES_DISABLED) + _SYSTEM_TAIL


def _api_key() -> str:
    env = os.environ.get("ALBERT_API_KEY", "")
    if env:
        return env
    return AlbertSettings().api_key


def _base_url() -> str:
    env = os.environ.get("ALBERT_BASE_URL", "")
    if env:
        return env
    return AlbertSettings().base_url or _DEFAULT_BASE_URL


def fetch_models() -> List[tuple[str, Optional[str]]]:
    """Sync fetch of text-generation models for the dropdown."""
    choices: List[tuple[str, Optional[str]]] = [("Default", None)]
    key = _api_key()
    if not key:
        return choices
    try:
        resp = httpx.get(
            f"{_base_url()}/models",
            headers={"Authorization": f"Bearer {key}"},
            timeout=10,
        )
        resp.raise_for_status()
        _CHAT_TYPES = {"text-generation", "image-text-to-text"}
        for m in resp.json().get("data", []):
            if m.get("type") in _CHAT_TYPES:
                model_id = m["id"]
                choices.append((model_id, model_id))
    except Exception:
        pass
    return choices


class AlbertBackend:
    display_name = "Albert"
    model_choices: List[tuple[str, Optional[str]]] = [("Default", None)]
    supports_sessions = False

    def __init__(self, ctx: BackendContext):
        key = _api_key()
        if not key:
            raise RuntimeError(
                "Albert API key not configured. Set it in "
                "Settings → Plugins → Albert, or via ALBERT_API_KEY env var."
            )
        self._base_url = _base_url()
        self._headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        self._tools_defs = _build_openai_tools(ctx.tools)
        self._handlers: Dict[str, callable] = {
            t["name"]: t["handler"] for t in ctx.tools
        }
        self._gated_names = {t["name"] for t in ctx.tools if t.get("gated")}
        self._confirm_cb = ctx.confirm_cb
        self._allow_writes = ctx.allow_writes
        self._tempdir = Path(ctx.tempdir)
        self._tempdir.mkdir(parents=True, exist_ok=True)
        self._model: Optional[str] = None
        self._history: List[dict] = []
        self._client = httpx.AsyncClient(timeout=120)

    async def ask(
        self, prompt: str, image_paths: Optional[List[str]] = None
    ) -> AsyncIterator[StreamBlock]:
        self._history.append({"role": "user", "content": prompt})

        while True:
            assistant_text = ""
            tool_calls: List[dict] = []

            request_body = self._build_request()
            async with self._client.stream(
                "POST",
                f"{self._base_url}/chat/completions",
                headers=self._headers,
                json=request_body,
            ) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise httpx.HTTPStatusError(
                        f"{resp.status_code}: {body.decode(errors='replace')}",
                        request=resp.request,
                        response=resp,
                    )
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    chunk = json.loads(payload)
                    choices = chunk.get("choices", [])
                    if not choices:
                        continue
                    delta = choices[0].get("delta", {})

                    # Text content
                    if "content" in delta and delta["content"]:
                        assistant_text += delta["content"]
                        yield TextBlock(text=delta["content"])

                    # Tool calls (streamed incrementally)
                    if "tool_calls" in delta:
                        for tc_delta in delta["tool_calls"]:
                            idx = tc_delta["index"]
                            while len(tool_calls) <= idx:
                                tool_calls.append(
                                    {"id": "", "function": {"name": "", "arguments": ""}}
                                )
                            tc = tool_calls[idx]
                            if tc_delta.get("id"):
                                tc["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if "name" in fn:
                                tc["function"]["name"] += fn["name"]
                            if "arguments" in fn:
                                tc["function"]["arguments"] += fn["arguments"]

            if not tool_calls:
                self._history.append({"role": "assistant", "content": assistant_text})
                break

            for tc in tool_calls:
                if not tc["id"]:
                    tc["id"] = f"call_{uuid.uuid4().hex[:24]}"

            self._history.append({
                "role": "assistant",
                "content": assistant_text or None,
                "tool_calls": [
                    {"id": tc["id"], "type": "function", "function": tc["function"]}
                    for tc in tool_calls
                ],
            })

            for tc in tool_calls:
                name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    args = {}

                result, images = await self._execute_tool(name, args)
                self._history.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
                for img in images:
                    yield img

    async def reset(self) -> None:
        self._history.clear()

    async def cancel(self) -> None:
        pass  # httpx streams are cancelled when the generator is abandoned

    async def resume(self, session_id: str) -> None:
        pass

    async def set_model(self, model: Optional[str]) -> None:
        self._model = model

    def set_allow_writes(self, allow: bool) -> None:
        self._allow_writes = allow

    async def list_slash_commands(self) -> List[str]:
        return []

    def list_sessions(self) -> List[SessionEntry]:
        return []

    def load_session(self, session_id: str, image_tempdir: Path) -> List[ChatMessage]:
        return []

    def _build_request(self) -> dict:
        model = self._model
        if not model:
            model = next((mid for _, mid in self.model_choices if mid), None)
        if not model:
            raise RuntimeError("no model selected — set one via the dropdown")
        settings = AlbertSettings()
        req = {
            "model": model,
            "messages": [{"role": "system", "content": _system_prompt(self._allow_writes)}] + self._history,
            "stream": True,
            "tools": self._tools_defs,
            "tool_choice": "auto",
            "temperature": settings.temperature,
            "top_p": settings.top_p,
        }
        if settings.max_completion_tokens > 0:
            req["max_completion_tokens"] = settings.max_completion_tokens
        return req

    async def _execute_tool(
        self, name: str, args: dict
    ) -> tuple[str, List[ImageBlock]]:
        images: List[ImageBlock] = []

        if name in self._gated_names:
            if not self._allow_writes:
                return (
                    "write actions disabled — ask user to toggle 'Allow write actions'",
                    images,
                )
            if self._confirm_cb:
                try:
                    allowed = await self._confirm_cb(name, args)
                except Exception as e:
                    return f"approval callback failed: {e}", images
                if not allowed:
                    return "user denied the tool call", images

        handler = self._handlers.get(name)
        if handler is None:
            return f"unknown tool: {name}", images

        try:
            result = handler(args)
            if asyncio.iscoroutine(result):
                result = await result
        except Exception as e:
            return f"{type(e).__name__}: {e}", images

        if isinstance(result, dict) and "content" in result:
            text_parts = []
            for item in result["content"]:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif item.get("type") == "image":
                    path = write_b64_image(
                        item.get("data"),
                        item.get("mimeType", "image/png"),
                        self._tempdir,
                        prefix="tool",
                    )
                    if path:
                        images.append(ImageBlock(path=path))
            return "\n".join(text_parts) or "OK", images

        return str(result), images


def _build_openai_tools(tools: List[dict]) -> List[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]

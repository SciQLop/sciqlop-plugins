"""GitHub Copilot chat backend — OpenAI-shaped chat completions with tool calling.

Shape mirrors sciqlop_albert's backend; the differences are:
- auth is a short-lived Copilot token refreshed from a stored GitHub OAuth token;
- Copilot-specific headers are required on every request.
"""
from __future__ import annotations

import asyncio
import json
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

from .auth import CopilotTokenCache, editor_headers
from .settings import CopilotSettings, load_github_token

_SYSTEM_PROMPT = """\
You are a helper embedded inside SciQLop, a Qt desktop application for \
space-physics time-series visualization. You act on the live running \
instance through function calls.

RULES:
- To find plottable products, ALWAYS use sciqlop_products_tree. Start with \
path="" to list providers, then drill down level by level using "//" as separator.
- NEVER guess product paths. Always discover them step by step.
- After plotting, ALWAYS call sciqlop_wait_for_plot_data before taking a screenshot.
- Call sciqlop_api_reference BEFORE writing any Python code.
- NEVER invent error messages or code; only report what tools returned.
- If a tool returns an error, read the message and retry with corrected arguments.

Be concise. Cite product names and time ranges verbatim.
"""

_WRITES_ENABLED = (
    "Write functions are ENABLED (user will be prompted to approve each call)."
)
_WRITES_DISABLED = (
    "Write functions are DISABLED. Do NOT call write tools — they will be rejected. "
    "Tell the user to enable 'Allow write actions' first."
)


def _system_prompt(allow_writes: bool) -> str:
    return _SYSTEM_PROMPT + "\n" + (_WRITES_ENABLED if allow_writes else _WRITES_DISABLED)


def _chat_models(token_cache: CopilotTokenCache) -> List[tuple[str, Optional[str]]]:
    """Fetch the catalog of chat-capable models from Copilot."""
    choices: List[tuple[str, Optional[str]]] = [("Default", None)]
    try:
        tok = token_cache.get()
        resp = httpx.get(
            f"{tok.api_base}/models",
            headers={
                "Authorization": f"Bearer {tok.token}",
                "Copilot-Integration-Id": "vscode-chat",
                **editor_headers(),
            },
            timeout=10,
        )
        resp.raise_for_status()
        for m in resp.json().get("data", []):
            caps = m.get("capabilities", {})
            if caps.get("type") != "chat":
                continue
            mid = m.get("id")
            if mid:
                label = m.get("name") or mid
                choices.append((label, mid))
    except Exception:
        pass
    return choices


def fetch_models() -> List[tuple[str, Optional[str]]]:
    token = load_github_token()
    if not token:
        return [("Default", None)]
    return _chat_models(CopilotTokenCache(token))


class CopilotBackend:
    display_name = "GitHub Copilot"
    model_choices: List[tuple[str, Optional[str]]] = [("Default", None)]
    supports_sessions = False

    def __init__(self, ctx: BackendContext):
        self._main_window = ctx.main_window
        self._github_token: Optional[str] = None
        self._token_cache: Optional[CopilotTokenCache] = None
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

    def _refresh_token_cache(self) -> Optional[CopilotTokenCache]:
        """Pick up a token saved after this backend was created (via the
        in-dock sign-in button), without forcing a new session."""
        token = load_github_token()
        if not token:
            self._github_token = None
            self._token_cache = None
            return None
        if token != self._github_token or self._token_cache is None:
            self._github_token = token
            self._token_cache = CopilotTokenCache(token)
        return self._token_cache

    async def ask(
        self, prompt: str, image_paths: Optional[List[str]] = None
    ) -> AsyncIterator[StreamBlock]:
        if self._refresh_token_cache() is None:
            raise RuntimeError(
                "GitHub Copilot not signed in. Click 'Sign in to GitHub Copilot' "
                "in the Agents dock header."
            )
        self._history.append({"role": "user", "content": prompt})

        while True:
            assistant_text_parts: List[str] = []
            tool_calls: List[dict] = []

            request_body = self._build_request()
            headers = self._request_headers()
            url = f"{self._token_cache.get().api_base}/chat/completions"

            async for block in _stream_sse(
                url, headers, request_body, assistant_text_parts, tool_calls
            ):
                yield block

            assistant_text = "".join(assistant_text_parts)
            tool_calls = [
                tc for tc in tool_calls
                if (tc.get("function", {}).get("name") or "").strip()
            ]

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
        pass

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

    def _request_headers(self) -> dict:
        tok = self._token_cache.get()
        return {
            "Authorization": f"Bearer {tok.token}",
            "Content-Type": "application/json",
            "Copilot-Integration-Id": "vscode-chat",
            "Openai-Intent": "conversation-panel",
            **editor_headers(),
        }

    def _build_request(self) -> dict:
        model = self._model
        if not model:
            model = next((mid for _, mid in self.model_choices if mid), None)
        if not model:
            raise RuntimeError("no model selected — set one via the dropdown")
        settings = CopilotSettings()
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


async def _stream_sse(
    url: str,
    headers: dict,
    body: dict,
    out_text: List[str],
    out_tool_calls: List[dict],
) -> AsyncIterator[TextBlock]:
    """Stream OpenAI-shaped SSE. Yields text blocks as they arrive; also
    collects assistant text and tool-call deltas into the given lists.

    Uses *sync* httpx in a worker thread and bridges chunks to the async
    side through an asyncio.Queue. This avoids the anyio 'cancel scope in
    a different task' noise that httpx.AsyncClient produces under qasync.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    sentinel: object = object()
    error_holder: List[BaseException] = []

    def put(item) -> None:
        loop.call_soon_threadsafe(queue.put_nowait, item)

    def consume_line(line: str) -> None:
        if not line.startswith("data: "):
            return
        data = line[6:]
        if data.strip() == "[DONE]":
            return
        chunk = json.loads(data)
        choices = chunk.get("choices", [])
        if not choices:
            return
        delta = choices[0].get("delta", {})
        if "content" in delta and delta["content"]:
            out_text.append(delta["content"])
            put(TextBlock(text=delta["content"]))
        if "tool_calls" in delta:
            for tc_delta in delta["tool_calls"]:
                idx = tc_delta["index"]
                while len(out_tool_calls) <= idx:
                    out_tool_calls.append(
                        {"id": "", "function": {"name": "", "arguments": ""}}
                    )
                tc = out_tool_calls[idx]
                if tc_delta.get("id"):
                    tc["id"] = tc_delta["id"]
                fn = tc_delta.get("function", {})
                if "name" in fn:
                    tc["function"]["name"] += fn["name"]
                if "arguments" in fn:
                    tc["function"]["arguments"] += fn["arguments"]

    def blocking_reader() -> None:
        try:
            with httpx.Client(timeout=120) as client:
                with client.stream("POST", url, headers=headers, json=body) as resp:
                    if resp.status_code >= 400:
                        payload = resp.read()
                        raise httpx.HTTPStatusError(
                            f"{resp.status_code}: {payload.decode(errors='replace')}",
                            request=resp.request,
                            response=resp,
                        )
                    for line in resp.iter_lines():
                        consume_line(line)
        except BaseException as e:
            error_holder.append(e)
        finally:
            put(sentinel)

    future = loop.run_in_executor(None, blocking_reader)
    try:
        while True:
            item = await queue.get()
            if item is sentinel:
                break
            yield item
    finally:
        try:
            await future
        except BaseException:
            pass

    if error_holder:
        raise error_holder[0]

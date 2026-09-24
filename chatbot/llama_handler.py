from __future__ import annotations
import asyncio
import json
import re
import sys
from typing import Any, Dict, List, Optional

from openai import OpenAI
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langfuse_integration import tracker, trace_function

from sql_dump import (
    SQLDumpRAG,
    SYSTEM_PROMPT,
    DEBUG,
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    OPENROUTER_MODELS,
    LOCAL_LLM_BASE_URL,
)

_REFUSAL_PATTERNS = re.compile(
    r"(as an ai( language model)?|i (can(not|'t)|am not able to|won'?t) "
    r"(help|assist|provide|answer|continue)|i'?m (unable|not able) to (help|assist|provide)|"
    r"against (my|the) (guidelines|policy|programming)|i must decline|"
    r"i cannot (fulfill|comply)|content policy|not appropriate for me to)",
    re.IGNORECASE,
)

_THOUGHT_BLOCK = re.compile(r"<thought>.*?</thought>", re.IGNORECASE | re.DOTALL)


def _strip_thought(text: str) -> str:
    """Remove any leaked <thought>...</thought> reasoning block so only the
    final answer is shown to the user."""
    if not text:
        return text
    return _THOUGHT_BLOCK.sub("", text).strip()

def _looks_like_bad_answer(text: str) -> bool:
    """True if a response should be treated as a failure and retried on the
    next model — either empty/near-empty, or a generic safety-style refusal
    that has nothing to do with an academic-database question."""
    if not text or len(text.strip()) < 2:
        return True
    if _REFUSAL_PATTERNS.search(text):
        return True
    return False

# MCP server subprocess: `python mcp_tools.py`, same interpreter as this process.
_MCP_SERVER_PARAMS = StdioServerParameters(command=sys.executable, args=["mcp_tools.py"])


def _tool_to_openai_schema(tool: Any) -> Dict[str, Any]:
    # mcp SDK < 2.0 uses `inputSchema`; >= 2.0 renamed it to `input_schema`.
    schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description or "",
            "parameters": schema,
        },
    }


def _history_to_messages(
    history: List[Dict[str, str]], max_turns: int = 2
) -> List[Dict[str, str]]:
    messages = []
    for turn in history[-(max_turns * 2):]:
        role = "user" if turn["role"] == "user" else "assistant"
        content = turn["content"]
        if role == "assistant" and len(content) > 150:
            content = content[:150] + "..."
        messages.append({"role": role, "content": content})
    return messages


class LlamaHandler:
    def __init__(self, rag: SQLDumpRAG) -> None:
        self.rag = rag
        self._session = None
        self._tools_cache = None
        self._lock = asyncio.Lock()
        # Keep references to the raw stdio context managers so we can
        # tear them down cleanly on close()/error, instead of only ever
        # holding the ClientSession that wraps them.
        self._stdio_ctx = None
        self._session_ctx = None

    # ── Persistent MCP session management ──
    async def _get_session(self):
        """Reuse the MCP session to avoid per-call startup and initialization."""
        async with self._lock:
            if self._session is None:
                self._stdio_ctx = stdio_client(_MCP_SERVER_PARAMS)
                read, write = await self._stdio_ctx.__aenter__()

                self._session_ctx = ClientSession(read, write)
                session = await self._session_ctx.__aenter__()
                await session.initialize()

                tools_resp = await session.list_tools()
                self._tools_cache = [_tool_to_openai_schema(t) for t in tools_resp.tools]
                self._session = session
        return self._session, self._tools_cache

    async def _reset_session(self) -> None:
        """Clear the cached session after errors to avoid reusing a dead connection."""
        async with self._lock:
            self._session = None
            self._tools_cache = None
            self._stdio_ctx = None
            self._session_ctx = None

    async def close(self) -> None:
        """Cleanly close the MCP subprocess during app shutdown."""
        async with self._lock:
            if self._session_ctx is not None:
                try:
                    await self._session_ctx.__aexit__(None, None, None)
                except Exception:
                    pass
            if self._stdio_ctx is not None:
                try:
                    await self._stdio_ctx.__aexit__(None, None, None)
                except Exception:
                    pass
            self._session = None
            self._tools_cache = None
            self._stdio_ctx = None
            self._session_ctx = None

    # ── MCP tool-calling path (replaces the old _build_context text-blob flow) ──
    @trace_function("LlamaHandler.handle")
    async def handle(
        self,
        question: str,
        history: List[Dict[str, str]],
        state: Optional[Any] = None,
        trace_id: Optional[str] = None,
        role: str = "admin",
        allowed_sem: Optional[int] = None,
    ) -> Optional[str]:
        """Use MCP tools for cross-table reasoning with chained calls.
        Async to preserve the persistent MCP session across requests."""
        try:
            return await self._handle_with_tools(
                question, history, trace_id, role=role, allowed_sem=allowed_sem
            )
        except Exception as e:
            if DEBUG:
                print(f"[LlamaHandler] MCP tool-calling failed: {e}")
            # The session may be in a bad state (broken pipe, dead
            # subprocess, etc.) — drop it so the next call reconnects
            # instead of repeatedly failing against a dead session.
            await self._reset_session()
            return None

    async def _handle_with_tools(
        self,
        question: str,
        history: List[Dict[str, str]],
        trace_id: Optional[str] = None,
        max_tool_rounds: int = 10,
        role: str = "admin",
        allowed_sem: Optional[int] = None,
    ) -> Optional[str]:
        _span = tracker.span_llm(trace_id, question, 0, OPENROUTER_MODEL)

        session, openai_tools = await self._get_session()

        messages = _history_to_messages(history) + [
            {"role": "user", "content": question}
        ]
        client = OpenAI(api_key=OPENROUTER_API_KEY, base_url=LOCAL_LLM_BASE_URL)

        total_prompt_tokens = 0
        total_completion_tokens = 0

        for round_i in range(max_tool_rounds):
            for model in OPENROUTER_MODELS:
                try:
                    resp = client.chat.completions.create(
                        model=model,
                        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                        tools=openai_tools,
                        temperature=0.2,
                        # 1200 was cutting off any answer that had to list many
                        # records (a division roster, "all faculty", etc.) —
                        # the model would run out of tokens mid-list and the
                        # reply would look like only "a few" were returned.
                        # list_people() intentionally returns the FULL match
                        # set uncapped, so the completion budget has to be
                        # big enough to actually narrate all of it back.
                        max_tokens=8192,
                        extra_headers={
                            "HTTP-Referer": "https://dpniti.local",
                            "X-Title": "DPNITI Campus Assist",
                        },
                    )
                    msg = resp.choices[0].message
                    usage = getattr(resp, "usage", None)
                    if usage:
                        total_prompt_tokens += getattr(usage, "prompt_tokens", 0) or 0
                        total_completion_tokens += getattr(usage, "completion_tokens", 0) or 0
                    break
                except Exception as e:
                    if DEBUG:
                        print(f"[LlamaHandler] '{model}' failed: {e}")
                    msg = None
                    continue
            if msg is None:
                tracker.end_span(_span, error="all models failed")
                return None

            if not msg.tool_calls:
                result = _strip_thought((msg.content or "").strip())
                if _looks_like_bad_answer(result):
                    tracker.end_span(_span, error="empty/refusal-style reply")
                    return None
                tracker.end_span(_span, output={
                    "response_length": len(result),
                    "rounds": round_i + 1,
                    "prompt_tokens": total_prompt_tokens,
                    "completion_tokens": total_completion_tokens,
                })
                return result

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ],
            })
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                args["access_role"] = role
                args["allowed_sem"] = allowed_sem
                try:
                    result = await session.call_tool(call.function.name, args)
                    text = "".join(getattr(b, "text", "") for b in result.content)
                except Exception as e:
                    text = json.dumps({"error": str(e)})
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": text,
                })

        tracker.end_span(_span, error="max tool rounds exceeded")
        return "I wasn't able to resolve that in time — could you rephrase or simplify the question?"

    # OpenRouter service available chhe ke nahi te check kare chhe.
    @staticmethod
    def is_available() -> bool:
        try:
            client = OpenAI(
                api_key=OPENROUTER_API_KEY,
                base_url=LOCAL_LLM_BASE_URL,
            )
            client.models.list()
            return True
        except Exception:
            return False
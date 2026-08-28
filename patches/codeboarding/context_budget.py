"""Context-window budget for CodeBoarding's ReAct agent loop (2repo patch).

Installed into CodeBoarding's venv as ``codeboarding_context_budget`` by
``patches/codeboarding/apply.py`` and wired into ``agents/agent.py`` as a
``create_agent`` middleware.

WHY
────────────────────────────────────────────────────────────────────────────
CodeBoarding's agent explores a component by calling tools (``readFile`` returns
a few hundred lines per call, several calls per turn, up to 40 graph steps) and
every tool result is appended to one conversation. Nothing bounds that growth:
CodeBoarding detects the model's *architectural* context length (262k for a
Qwen-class model) but never uses it, and a local Ollama server runs a much
smaller window (``OLLAMA_CONTEXT_LENGTH``, typically 32k). When the prompt
crosses that window Ollama silently drops the oldest tokens — the system prompt
and the task — and the turn comes back empty or as a 500. CodeBoarding then
retries the whole component from scratch, up to five times, and the final result
is degraded anyway. On a 24 GB GPU with a 27B model this was the dominant
failure mode of ``2repo arch``.

WHAT
────────────────────────────────────────────────────────────────────────────
A ``wrap_tool_call`` middleware that knows the real window (``CODEBOARDING_CONTEXT_WINDOW``,
set by ``repo/arch.py`` from ``OLLAMA_NUM_CTX`` / ``REPO_ARCH_CONTEXT_TOKENS``) and,
before every tool result is handed back to the model:

1. measures how full the conversation already is — exactly, from the
   ``usage_metadata`` Ollama/OpenAI/Anthropic attach to the last AI turn
   (``input_tokens`` = the prompt the model just saw), with a character-based
   estimate as a fallback;
2. if the conversation is past the stop line (``CODEBOARDING_CONTEXT_STOP_FRACTION``
   × window, default 0.8), does not run the tool and instead returns a message
   telling the model to stop reading and write its final answer;
3. otherwise runs the tool and, if the result would push the conversation past
   the stop line, truncates it to the remaining room (split evenly across the
   tool calls of the same turn, since they run before any of them lands in state).

The model always gets a well-formed, in-window prompt, so the worst case becomes
"a slightly less thorough component description" instead of "five wasted
retries and garbage". With no ``CODEBOARDING_CONTEXT_WINDOW`` the middleware is a
no-op, so cloud presets and stock behaviour are untouched.

Per-invocation state lives in the message history the agent already carries
(``request.state["messages"]``), so the middleware itself holds no mutable state
and is safe to share across CodeBoarding's concurrently running agents.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ToolCallRequest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

logger = logging.getLogger("codeboarding_context_budget")

ENV_WINDOW = "CODEBOARDING_CONTEXT_WINDOW"
ENV_STOP_FRACTION = "CODEBOARDING_CONTEXT_STOP_FRACTION"
DEFAULT_STOP_FRACTION = 0.8

# Rough tokenizer-free estimate for source code with line-number prefixes. Slightly
# pessimistic on purpose: under-estimating a tool result's cost is the failure we
# are guarding against, over-estimating only trims a little more.
CHARS_PER_TOKEN = 3.5

# Below this much room a truncated tool result would be too short to be useful;
# better to stop reading altogether and let the model answer.
MIN_USEFUL_TOKENS = 256

STOP_MESSAGE = (
    "Context budget reached: the conversation is close to the model's context window, "
    "so no more tool output can be returned. Do NOT call any more tools. Write your "
    "final answer now, in the requested format, using only the information you have "
    "already gathered."
)

TRUNCATION_NOTE = (
    "\n\n[... output truncated: context budget reached. Do not request more of this "
    "file or call further tools — finish your answer with what you have.]"
)


def context_window() -> int | None:
    """The model's usable context window in tokens, or None when unconfigured."""
    raw = os.environ.get(ENV_WINDOW, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; context budget disabled", ENV_WINDOW, raw)
        return None
    return value if value > 0 else None


def stop_fraction() -> float:
    raw = os.environ.get(ENV_STOP_FRACTION, "").strip()
    if not raw:
        return DEFAULT_STOP_FRACTION
    try:
        value = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; using %s", ENV_STOP_FRACTION, raw, DEFAULT_STOP_FRACTION)
        return DEFAULT_STOP_FRACTION
    # Clamp to something sane: below 0.1 nothing could ever run, above 1.0 the
    # guard would fire after the overflow it exists to prevent.
    return min(1.0, max(0.1, value))


def estimate_tokens(text: str) -> int:
    return max(1, int(len(text) / CHARS_PER_TOKEN))


def _message_chars(message: BaseMessage) -> int:
    content = message.content
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return sum(len(part if isinstance(part, str) else str(part)) for part in content)
    return len(str(content))


def conversation_usage(messages: Sequence[BaseMessage]) -> tuple[int, int]:
    """Return (tokens_in_conversation, tool_calls_in_current_turn).

    The conversation size is taken from the last AI message's ``usage_metadata``:
    ``input_tokens`` is exactly the prompt the model saw for that turn and
    ``output_tokens`` what it added, so their sum is the whole history up to and
    including the tool calls now being executed. Providers that report no usage
    fall back to a character estimate over every message.
    """
    last_ai: AIMessage | None = None
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            last_ai = message
            break

    calls = len(last_ai.tool_calls) if last_ai is not None and last_ai.tool_calls else 1

    usage = getattr(last_ai, "usage_metadata", None) if last_ai is not None else None
    if usage and usage.get("input_tokens"):
        return int(usage["input_tokens"]) + int(usage.get("output_tokens") or 0), calls

    chars = sum(_message_chars(m) for m in messages)
    return estimate_tokens("x" * chars) if chars else 0, calls


class ContextBudgetMiddleware(AgentMiddleware):
    """Keep CodeBoarding's tool loop inside the model's real context window."""

    name = "context_budget"

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        window = context_window()
        if window is None:
            return handler(request)

        limit = int(window * stop_fraction())
        messages = request.state.get("messages", []) if isinstance(request.state, dict) else []
        used, siblings = conversation_usage(messages)
        # Sibling tool calls of the same turn execute before any of their results
        # reach the state, so each one may only claim its share of the room.
        room = (limit - used) // max(1, siblings)

        tool_call = request.tool_call
        tool_name = tool_call.get("name", "tool")
        tool_call_id = tool_call.get("id", "")

        if room < MIN_USEFUL_TOKENS:
            logger.warning(
                "[ContextBudget] %s skipped: conversation at %d/%d tokens (limit %d) — asking the model to finish",
                tool_name, used, window, limit,
            )
            return ToolMessage(content=STOP_MESSAGE, tool_call_id=tool_call_id, name=tool_name)

        result = handler(request)
        if not isinstance(result, ToolMessage) or not isinstance(result.content, str):
            return result

        cost = estimate_tokens(result.content)
        if cost <= room:
            return result

        keep_chars = max(0, int(room * CHARS_PER_TOKEN) - len(TRUNCATION_NOTE))
        logger.warning(
            "[ContextBudget] %s result truncated from ~%d to ~%d tokens (conversation %d/%d, limit %d)",
            tool_name, cost, room, used, window, limit,
        )
        return result.model_copy(update={"content": result.content[:keep_chars] + TRUNCATION_NOTE})

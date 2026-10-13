"""
Same job as anthropic_runner.py, but drives a local Ollama server
instead of the Anthropic API - no API key, no cost, runs on your
own machine.

Ollama's /api/chat endpoint accepts an OpenAI-style "tools" list and
returns tool_calls on message.tool_calls, so the shape of this loop
mirrors anthropic_runner.py closely - same public signature
(run_tool_loop), same AgentToolError - only the request/response
translation differs.

Requires the Ollama app/service running locally (ollama.com) and the
model already pulled, e.g.:
    ollama pull qwen3:8b
"""

import json
import os
from typing import Callable, Optional

import requests

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
DEFAULT_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
MAX_TURNS = 8
# CPU-only inference can be slow, especially the first request after
# the model isn't already loaded in RAM (Ollama has to load it from
# disk first). 120s was too short and caused ReadTimeout errors on
# CPU-only machines - override with OLLAMA_TIMEOUT_SECONDS in .env if
# you need even more.
REQUEST_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "30"))
DEBUG = os.getenv("AGENT_DEBUG", "").strip() == "1"


def _debug(msg: str) -> None:
    if DEBUG:
        print(f"[ollama_runner] {msg}")


class AgentToolError(RuntimeError):
    """Raised when a tool call fails in a way the loop can't recover from."""


def _to_ollama_tool(anthropic_style_tool: dict) -> dict:
    """Anthropic's {name, description, input_schema} -> Ollama/OpenAI's
    {type: function, function: {name, description, parameters}}."""

    return {
        "type": "function",
        "function": {
            "name": anthropic_style_tool["name"],
            "description": anthropic_style_tool["description"],
            "parameters": anthropic_style_tool["input_schema"],
        },
    }


def run_tool_loop(
    system_prompt: str,
    user_message: str,
    tools: list,
    tool_dispatch: dict,
    submit_tool_name: str,
    max_turns: int = MAX_TURNS,
    model: str = DEFAULT_MODEL,
) -> dict:
    """
    Same contract as anthropic_runner.run_tool_loop: drives the loop
    and returns the dict the model passed to `submit_tool_name`.
    """

    ollama_tools = [_to_ollama_tool(t) for t in tools]

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    for turn_number in range(max_turns):
        _debug(f"--- turn {turn_number + 1}/{max_turns}: asking {model} ---")

        try:
            response = requests.post(
                f"{OLLAMA_HOST}/api/chat",
                json={
                    "model": model,
                    "messages": messages,
                    "tools": ollama_tools,
                    "stream": False,
                },
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except requests.exceptions.ConnectionError as exc:
            raise AgentToolError(
                f"Could not reach Ollama at {OLLAMA_HOST}. Is the Ollama "
                "app/service running? (`ollama --version` to check, "
                "`ollama serve` to start it manually)"
            ) from exc
        except requests.exceptions.ReadTimeout as exc:
            raise AgentToolError(
                f"Ollama didn't respond within {REQUEST_TIMEOUT_SECONDS}s. "
                "On CPU-only machines the model can be slow to load the "
                "first time - try running `ollama run qwen3:8b \"hi\"` once "
                "in a separate terminal to warm it up, then try again. If "
                "it's still too slow, raise OLLAMA_TIMEOUT_SECONDS in .env, "
                "or switch to a smaller model (qwen3:4b) in OLLAMA_MODEL."
            ) from exc

        data = response.json()
        message = data["message"]
        messages.append(message)

        tool_calls = message.get("tool_calls") or []

        if not tool_calls:
            _debug(f"model replied with plain text instead of a tool call: {message.get('content', '')[:200]!r}")
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"You must call the '{submit_tool_name}' tool to "
                        "finish, not reply in plain text. If you don't have "
                        "enough information yet, call one of the lookup "
                        "tools first."
                    ),
                }
            )
            continue

        for call in tool_calls:
            function = call["function"]
            name = function["name"]
            arguments = function.get("arguments", {})

            if isinstance(arguments, str):
                arguments = json.loads(arguments)

            if name == submit_tool_name:
                _debug(f"model called {name} - finishing.")
                return arguments

            handler: Optional[Callable] = tool_dispatch.get(name)

            if handler is None:
                _debug(f"model called unknown tool {name!r}")
                result_content = f"Unknown tool '{name}'."
            else:
                _debug(f"model called {name}({arguments})")
                try:
                    result = handler(**arguments)
                    result_content = json.dumps(result, default=str)
                    _debug(f"  -> {result_content[:300]}")
                except Exception as exc:  # noqa: BLE001 - surfaced to the model
                    result_content = json.dumps({"error": str(exc)})
                    _debug(f"  -> ERROR: {exc}")

            messages.append({"role": "tool", "content": result_content})

    raise AgentToolError(
        f"Model did not call '{submit_tool_name}' within {max_turns} turns. "
        "Small local models sometimes need more turns or clearer prompting - "
        "try increasing max_turns, or a larger model if this happens often."
    )

"""
Generic Claude tool-use loop, shared by every subagent.

Pattern used across the agentic layer:
    1. Give the model a system prompt + a set of read-only DB tools.
    2. Also give it ONE "submit_result" tool whose input_schema IS the
       subagent's structured output contract.
    3. Loop: model calls tools, we execute them and feed results back,
       until the model calls submit_result - that's the only way the
       loop ends successfully. This avoids parsing free-text JSON out
       of a final message, which is brittle.

Each subagent (property_identification, document_processing, ...)
provides its own tools + submit-tool name; this module only knows how
to drive the loop.

Requires ANTHROPIC_API_KEY set in .env and billing enabled at
console.anthropic.com - separate from a claude.ai subscription.
"""

import json
import os
from typing import Callable, Optional

import anthropic

DEFAULT_MODEL = "claude-sonnet-4-6"
MAX_TURNS = 8


class AgentToolError(RuntimeError):
    """Raised when a tool call fails in a way the loop can't recover from."""


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
    Drive the tool-use loop and return the input dict the model passed
    to `submit_tool_name` once it calls it.

    tools:          list of Anthropic tool schemas (dicts)
    tool_dispatch:  {tool_name: callable(**tool_input) -> JSON-serializable}
                    does NOT need an entry for submit_tool_name
    submit_tool_name: name of the tool that ends the loop

    Raises AgentToolError if the model never calls submit_tool_name
    within max_turns, or if it calls an unknown tool repeatedly.
    """

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    messages = [{"role": "user", "content": user_message}]

    for _turn in range(max_turns):
        response = client.messages.create(
            model=model,
            max_tokens=2000,
            system=system_prompt,
            tools=tools,
            messages=messages,
        )

        messages.append({"role": "assistant", "content": response.content})

        tool_use_blocks = [b for b in response.content if b.type == "tool_use"]

        if not tool_use_blocks:
            # Model responded with plain text instead of calling a
            # tool - nudge it back on track rather than failing hard.
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

        tool_results = []

        for block in tool_use_blocks:
            if block.name == submit_tool_name:
                return block.input

            handler: Optional[Callable] = tool_dispatch.get(block.name)

            if handler is None:
                result_content = f"Unknown tool '{block.name}'."
            else:
                try:
                    result = handler(**block.input)
                    result_content = json.dumps(result, default=str)
                except Exception as exc:  # noqa: BLE001 - surfaced to the model
                    result_content = json.dumps({"error": str(exc)})

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result_content,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    raise AgentToolError(
        f"Model did not call '{submit_tool_name}' within {max_turns} turns."
    )
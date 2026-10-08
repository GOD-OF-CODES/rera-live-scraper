"""
Picks which LLM backend drives the tool-calling loop, based on
AGENT_LLM_BACKEND in .env. Everything else in the agents/ folder
imports run_tool_loop and AgentToolError from HERE, not from
anthropic_runner.py or ollama_runner.py directly - that's what lets
you switch backends by changing one line in .env instead of editing
code.

AGENT_LLM_BACKEND=ollama     -> local, free, needs Ollama running (default)
AGENT_LLM_BACKEND=anthropic  -> Claude API, needs ANTHROPIC_API_KEY + billing
"""

import os

_BACKEND = os.getenv("AGENT_LLM_BACKEND", "ollama").strip().lower()

if _BACKEND == "anthropic":
    from agents.common.anthropic_runner import AgentToolError, run_tool_loop # type: ignore
elif _BACKEND == "ollama":
    from agents.common.ollama_runner import AgentToolError, run_tool_loop # type: ignore
else:
    raise ValueError(
        f"Unknown AGENT_LLM_BACKEND={_BACKEND!r} in .env - "
        "expected 'ollama' or 'anthropic'."
    )

__all__ = ["run_tool_loop", "AgentToolError"]
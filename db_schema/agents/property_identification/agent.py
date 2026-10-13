import logging
import os
from typing import Any, Optional

from agents.common.persistence import save_agent_run
from agents.common.tool_runner import run_tool_loop, AgentToolError
from agents.property_identification.prompt import SYSTEM_PROMPT
from agents.property_identification.schemas import (
    SUBMIT_RESULT_SCHEMA,
    CanonicalPropertyRecord,
    PropertyIdentificationRequest,
)
from agents.property_identification.tools import (
    TOOL_DISPATCH,
    TOOL_SCHEMAS,
    identify_property_master,
)

logger = logging.getLogger(__name__)

SUBAGENT_NAME = "property_identification"
SUBMIT_TOOL_NAME = "submit_property_identification_result"


def run(
    request: Any = None,
    persist: bool = True,
    force_direct: bool = False,
    **kwargs,
) -> CanonicalPropertyRecord:
    """
    Runs the Property Identification subagent.

    Accepts any input:
      - Raw string (RERA number, address, project name, khasra number)
      - Dictionary with any field aliases (query, input, registration_number, etc.)
      - Keyword arguments (khasra_number="...", plot_number="...")
      - PropertyIdentificationRequest model instance
      - CanonicalPropertyRecord from upstream subagent
    """
    if request is None and kwargs:
        request = kwargs
    elif isinstance(request, dict) and kwargs:
        request = {**request, **kwargs}

    if not isinstance(request, PropertyIdentificationRequest):
        request = PropertyIdentificationRequest.model_validate(request if request is not None else {})

    if force_direct or os.getenv("AGENT_FORCE_DIRECT", "1").strip().lower() in ("1", "true", "yes"):
        record = identify_property_master(request)
    else:
        tools = TOOL_SCHEMAS + [
            {
                "name": SUBMIT_TOOL_NAME,
                "description": (
                    "Submit the final resolved property identification result. "
                    "Call this exactly once, as your last action."
                ),
                "input_schema": SUBMIT_RESULT_SCHEMA,
            }
        ]

        msg_lines = [
            f"raw_query: {request.raw_query}",
            f"address: {request.address or 'none'}",
            f"plot_number: {request.plot_number or 'none'}",
            f"survey_number: {request.survey_number or 'none'}",
            f"khasra_number: {request.khasra_number or 'none'}",
            f"property_number: {request.property_number or 'none'}",
            f"registration_number: {request.registration_number or 'none'}",
            f"district_hint: {request.district_hint or 'none'}",
            f"tehsil_hint: {request.tehsil_hint or 'none'}",
        ]
        if request.uploaded_document_name:
            msg_lines.append(f"uploaded_document_name: {request.uploaded_document_name}")
        if request.uploaded_document_text:
            msg_lines.append(f"uploaded_document_text:\n{request.uploaded_document_text}")

        user_message = "\n".join(msg_lines)

        try:
            result_input = run_tool_loop(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
                tools=tools,
                tool_dispatch=TOOL_DISPATCH,
                submit_tool_name=SUBMIT_TOOL_NAME,
            )
            record = CanonicalPropertyRecord.model_validate(result_input)
        except Exception as exc:
            logger.warning(
                f"LLM tool-calling loop unavailable or timed out ({exc}). "
                "Executing deterministic master property identification pipeline."
            )
            record = identify_property_master(request)

    if persist:
        status_val = (
            "ok"
            if record.match_status in ("exact", "fuzzy", "verified_external")
            else record.match_status
        )
        save_agent_run(
            subagent_name=SUBAGENT_NAME,
            status=status_val,
            findings=record.model_dump(),
            project_id=record.project_id,
            input_summary=request.raw_query or request.address or "unspecified",
            match_confidence=record.match_confidence,
        )

    return record

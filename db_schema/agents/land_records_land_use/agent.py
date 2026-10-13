import logging
import os

from agents.common.persistence import save_agent_run
from agents.common.tool_runner import run_tool_loop, AgentToolError
from agents.land_records_land_use.prompt import SYSTEM_PROMPT
from agents.land_records_land_use.schemas import (
    SUBMIT_RESULT_SCHEMA,
    LandRecordsLandUseRecord,
    LandRecordsLandUseRequest,
)
from agents.land_records_land_use.tools import (
    TOOL_DISPATCH,
    TOOL_SCHEMAS,
    audit_land_records_and_use,
)

logger = logging.getLogger(__name__)

SUBAGENT_NAME = "land_records_land_use"
SUBMIT_TOOL_NAME = "submit_land_records_land_use_result"


from typing import Any

def run(
    request: Any = None,
    persist: bool = True,
    force_direct: bool = False,
    **kwargs,
) -> LandRecordsLandUseRecord:
    """
    Runs the Land Records & Land Use subagent.
    Accepts raw string, dict with any aliases, kwargs, upstream subagent output, or LandRecordsLandUseRequest.
    """
    if request is None and kwargs:
        request = kwargs
    elif isinstance(request, dict) and kwargs:
        request = {**request, **kwargs}

    if not isinstance(request, LandRecordsLandUseRequest):
        request = LandRecordsLandUseRequest.model_validate(request if request is not None else {})

    if force_direct or os.getenv("AGENT_FORCE_DIRECT", "1").strip().lower() in ("1", "true", "yes"):
        record = audit_land_records_and_use(request)
    else:
        tools = TOOL_SCHEMAS + [
            {
                "name": SUBMIT_TOOL_NAME,
                "description": (
                    "Submit the verified land records & land use result. Call this "
                    "exactly once, as your last action."
                ),
                "input_schema": SUBMIT_RESULT_SCHEMA,
            }
        ]

        user_message = (
            f"project_id (if provided): {request.project_id if request.project_id is not None else 'none'}\n"
            f"registration_number (if provided): {request.registration_number or 'none'}\n"
            f"khasra_number (if provided): {request.khasra_number or 'none'}\n"
            f"district_hint (if provided): {request.district_hint or 'none'}\n"
            f"cadastral_survey_number (if provided): {request.cadastral_survey_number or 'none'}\n"
            f"declared_land_use (if provided): {request.declared_land_use or 'none'}"
        )

        try:
            result_input = run_tool_loop(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
                tools=tools,
                tool_dispatch=TOOL_DISPATCH,
                submit_tool_name=SUBMIT_TOOL_NAME,
            )
            record = LandRecordsLandUseRecord.model_validate(result_input)
        except Exception as exc:
            logger.warning(
                f"LLM tool-calling loop unavailable or timed out ({exc}). "
                "Executing deterministic land records & use audit."
            )
            record = audit_land_records_and_use(request)

    if persist:
        save_agent_run(
            subagent_name=SUBAGENT_NAME,
            status="ok" if record.match_status in ("verified", "partial") else record.match_status,
            findings=record.model_dump(),
            project_id=record.project_id or request.project_id,
            input_summary=request.registration_number or (
                f"project_id={request.project_id}" if request.project_id is not None else "unspecified"
            ),
            evidence_refs=record.supporting_evidence,
        )

    return record

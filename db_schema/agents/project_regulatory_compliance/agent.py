import logging
import os

from agents.common.persistence import save_agent_run
from agents.common.tool_runner import run_tool_loop, AgentToolError
from agents.project_regulatory_compliance.prompt import SYSTEM_PROMPT
from agents.project_regulatory_compliance.schemas import (
    SUBMIT_RESULT_SCHEMA,
    ProjectRegulatoryComplianceRecord,
    ProjectRegulatoryComplianceRequest,
)
from agents.project_regulatory_compliance.tools import (
    TOOL_DISPATCH,
    TOOL_SCHEMAS,
    audit_project_and_regulatory_compliance,
)

logger = logging.getLogger(__name__)

SUBAGENT_NAME = "project_regulatory_compliance"
SUBMIT_TOOL_NAME = "submit_project_regulatory_compliance_result"


from typing import Any

def run(
    request: Any = None,
    persist: bool = True,
    force_direct: bool = False,
    **kwargs,
) -> ProjectRegulatoryComplianceRecord:
    """
    Runs the Project & Regulatory Compliance subagent.
    Accepts raw string, dict with any aliases, kwargs, upstream subagent output, or ProjectRegulatoryComplianceRequest.
    """
    if request is None and kwargs:
        request = kwargs
    elif isinstance(request, dict) and kwargs:
        request = {**request, **kwargs}

    if not isinstance(request, ProjectRegulatoryComplianceRequest):
        request = ProjectRegulatoryComplianceRequest.model_validate(request if request is not None else {})

    if force_direct or os.getenv("AGENT_FORCE_DIRECT", "1").strip().lower() in ("1", "true", "yes"):
        record = audit_project_and_regulatory_compliance(request)
    else:
        tools = TOOL_SCHEMAS + [
            {
                "name": SUBMIT_TOOL_NAME,
                "description": (
                    "Submit the final project & regulatory compliance result. Call this "
                    "exactly once, as your last action."
                ),
                "input_schema": SUBMIT_RESULT_SCHEMA,
            }
        ]

        user_message = (
            f"project_id (if provided): {request.project_id if request.project_id is not None else 'none'}\n"
            f"registration_number (if provided): {request.registration_number or 'none'}\n"
            f"promoter_name_hint (if provided): {request.promoter_name_hint or 'none'}\n"
            f"rera_project_id (if provided): {request.rera_project_id or 'none'}\n"
            f"authority_hint (if provided): {request.authority_hint or 'none'}"
        )

        try:
            result_input = run_tool_loop(
                system_prompt=SYSTEM_PROMPT,
                user_message=user_message,
                tools=tools,
                tool_dispatch=TOOL_DISPATCH,
                submit_tool_name=SUBMIT_TOOL_NAME,
            )
            record = ProjectRegulatoryComplianceRecord.model_validate(result_input)
        except Exception as exc:
            logger.warning(
                f"LLM tool-calling loop unavailable or timed out ({exc}). "
                "Executing deterministic regulatory compliance audit."
            )
            record = audit_project_and_regulatory_compliance(request)

    if persist:
        project_id_val = (
            record.project_details.project_id
            if record.project_details and record.project_details.project_id
            else request.project_id
        )
        save_agent_run(
            subagent_name=SUBAGENT_NAME,
            status="ok" if record.compliance_status in ("compliant", "partially_compliant") else record.compliance_status,
            findings=record.model_dump(),
            project_id=project_id_val,
            input_summary=request.registration_number or (
                f"project_id={request.project_id}" if request.project_id is not None else "unspecified"
            ),
            evidence_refs=record.supporting_evidence,
        )

    return record

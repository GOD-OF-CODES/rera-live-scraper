"""
Shared persistence helpers for the agentic layer.

Every subagent (property_identification, document_processing,
project_regulatory_compliance, cross_verification_risk, ...) writes its
output through save_agent_run() so all findings end up in one place
(agent_runs - see db/migrations/004_add_agent_runs.sql) with a
consistent shape. The Cross-Verification & Risk subagent will mostly
just call get_agent_runs_for_project() and reconcile.

Run from db_schema/ so the "db" package import below resolves the
same way api/main.py and scripts/backfill_db.py already do.
"""

from typing import Optional

from db.connection import get_cursor


def save_agent_run(
    subagent_name: str,
    status: str,
    findings: dict,
    project_id: Optional[int] = None,
    input_summary: Optional[str] = None,
    match_confidence: Optional[float] = None,
    risk_level: Optional[str] = None,
    risk_reasons: Optional[list] = None,
    evidence_refs: Optional[list] = None,
) -> int:
    """
    Insert one row into agent_runs and return its id.

    status should be one of: pending | ok | not_found | ambiguous | error
    """

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO agent_runs (
                project_id, subagent_name, status, input_summary,
                findings, match_confidence, risk_level, risk_reasons,
                evidence_refs
            )
            VALUES (
                %s, %s, %s, %s,
                %s::jsonb, %s, %s, %s::jsonb,
                %s::jsonb
            )
            RETURNING id
            """,
            [
                project_id,
                subagent_name,
                status,
                input_summary,
                _to_json(findings),
                match_confidence,
                risk_level,
                _to_json(risk_reasons),
                _to_json(evidence_refs),
            ],
        )

        return cur.fetchone()["id"]


def get_agent_runs_for_project(project_id: int, subagent_name: Optional[str] = None) -> list:
    """
    Every prior agent_runs row for a project, newest first. Pass
    subagent_name to filter to one subagent. This is the main read
    path the Cross-Verification & Risk subagent will use.
    """

    with get_cursor(commit=False) as cur:
        if subagent_name:
            cur.execute(
                """
                SELECT * FROM agent_runs
                WHERE project_id = %s AND subagent_name = %s
                ORDER BY created_at DESC
                """,
                [project_id, subagent_name],
            )
        else:
            cur.execute(
                """
                SELECT * FROM agent_runs
                WHERE project_id = %s
                ORDER BY created_at DESC
                """,
                [project_id],
            )

        return cur.fetchall()


def _to_json(value):
    import json

    if value is None:
        return None
    return json.dumps(value)

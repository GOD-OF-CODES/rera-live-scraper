-- Migration 004: agent_runs
--
-- WHY: none of the existing tables have anywhere to store what an
-- agentic subagent concluded about a project (identifiers resolved,
-- risk found, confidence, evidence). project_extensions is for RAW
-- SCRAPED RERA sections and shouldn't be reused for agent output -
-- mixing "what the source said" with "what our agent inferred" would
-- make both harder to trust and query.
--
-- Every subagent (Property Identification, Document Intelligence,
-- Regulatory Compliance, Cross-Verification, ...) writes ONE row here
-- per run. The Cross-Verification & Risk subagent's job is largely:
-- read every prior row for a project_id and reconcile them.
--
-- project_id is NULLABLE: Property Identification may run before a
-- project is confidently resolved (e.g. input didn't match anything),
-- so it needs to be able to log a "not_found" run with no project yet.

CREATE TABLE agent_runs (
    id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    project_id        BIGINT REFERENCES projects(id) ON DELETE CASCADE,

    subagent_name     VARCHAR(100) NOT NULL,
        -- e.g. 'property_identification', 'document_intelligence',
        -- 'project_regulatory_compliance', 'cross_verification_risk'

    status            VARCHAR(20) NOT NULL DEFAULT 'pending',
        -- pending | ok | not_found | ambiguous | error

    input_summary     TEXT,
        -- short human-readable record of what was asked, for audit/debug

    findings          JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- the subagent's structured output, shape is subagent-specific

    match_confidence  NUMERIC(4,3),
        -- 0.000-1.000, used by identification/matching-style subagents

    risk_level        VARCHAR(20),
        -- low | medium | high - set by risk-assessing subagents

    risk_reasons      JSONB,

    evidence_refs     JSONB,
        -- source URLs / document IDs / other agent_runs.id the
        -- conclusion is based on - keeps every finding traceable

    created_at        TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_agent_runs_project_id ON agent_runs(project_id);
CREATE INDEX idx_agent_runs_subagent   ON agent_runs(subagent_name);
CREATE INDEX idx_agent_runs_status     ON agent_runs(status);

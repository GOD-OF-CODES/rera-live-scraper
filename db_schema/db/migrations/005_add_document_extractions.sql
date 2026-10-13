-- Migration 005: document_extractions
--
-- WHY: project_documents (existing table) only stores the document
-- INDEX we scraped from UP-RERA - name, type, upload date, download
-- URL. It has never held the CONTENTS of a document.
--
-- We confirmed on a real record (UPRERAPRJ14636 / BALAJI GREENS) that
-- structured fields like land_details.khasra_plot_details and
-- registry_agreement_details are frequently empty at the RERA source,
-- while the actual "Registry Document In Case of Own Land" PDFs ARE
-- uploaded and downloadable. That gap is exactly what the Document
-- Processing tool exists to close: fetch the PDF, OCR/extract it, and
-- write ONE row per document here.
--
-- This table is the CONTRACT between the Document Processing tool and
-- every subagent that wants to read extracted document content
-- (Property Identification, Ownership & Title, Registration &
-- Encumbrance, ...). Whoever builds document processing should only
-- need to satisfy this shape; nothing else needs to change on their
-- side to plug into the rest of the agentic layer.

CREATE TABLE document_extractions (
    id                   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    project_document_id BIGINT NOT NULL
                         REFERENCES project_documents(id) ON DELETE CASCADE,

    project_id           BIGINT NOT NULL
                          REFERENCES projects(id) ON DELETE CASCADE,
        -- denormalized on purpose: lets every subagent query
        -- "give me everything extracted for project X" with one
        -- simple WHERE, no join through project_documents needed.

    extraction_status    VARCHAR(20) NOT NULL DEFAULT 'pending',
        -- pending | ok | failed | unreadable_scan

    document_category    VARCHAR(50),
        -- classified by the doc-processing tool, e.g.
        -- 'registry_deed' | 'sale_agreement' | 'architect_certificate'
        -- | 'engineer_certificate' | 'ca_certificate' | 'other'

    extracted_fields      JSONB NOT NULL DEFAULT '{}'::jsonb,
        -- structured fields pulled out of the document, e.g.
        -- {"khasra_number": "123/4", "seller_name": "...",
        --  "buyer_name": "...", "deed_date": "2016-03-11",
        --  "plot_area_sq_m": "450"}
        -- Field NAMES are up to the doc-processing tool/document type,
        -- deliberately not a fixed column list, since document types
        -- vary widely (registry deed vs. architect certificate vs.
        -- engineer certificate all extract different things).

    raw_text              TEXT,
        -- full OCR text dump, optional but recommended - lets other
        -- subagents (e.g. Litigation, Ownership) re-search text for
        -- fields the structured extractor didn't specifically target.

    confidence            NUMERIC(4,3),
        -- 0.000-1.000 OCR/extraction confidence

    source_document_url   TEXT,
        -- copy of project_documents.document_url at extraction time,
        -- so this row is self-contained even if the source URL rots

    extracted_at           TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    UNIQUE (project_document_id)
        -- one extraction record per source document; re-running
        -- extraction should UPDATE this row, not insert a duplicate
);

CREATE INDEX idx_document_extractions_project_id  ON document_extractions(project_id);
CREATE INDEX idx_document_extractions_document_id ON document_extractions(project_document_id);
CREATE INDEX idx_document_extractions_status      ON document_extractions(extraction_status);
CREATE INDEX idx_document_extractions_category    ON document_extractions(document_category);

-- Convenience view: one row per project showing what's been extracted
-- so far, mirroring the pattern of project_documents_view (migration 002).
CREATE VIEW project_document_extractions_view AS
SELECT
    de.project_id,
    p.registration_number,
    de.project_document_id,
    pd.document_name,
    pd.file_name,
    de.extraction_status,
    de.document_category,
    de.extracted_fields,
    de.confidence,
    de.extracted_at
FROM document_extractions de
JOIN project_documents pd ON pd.id = de.project_document_id
JOIN projects p ON p.id = de.project_id
ORDER BY de.project_id, de.project_document_id;

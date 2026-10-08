"""
Read/write helpers around document_extractions
(db/migrations/005_add_document_extractions.sql).

This is the ONLY table other subagents (Property Identification,
Ownership & Title, Registration & Encumbrance, ...) will read from -
whatever pipeline you build in extractor.py, land its output here in
this shape and everything else plugs in automatically.

Run from db_schema/, same convention as the rest of the codebase.
"""

from typing import Optional

from db.connection import get_cursor


def list_pending_documents(limit: int = 50) -> list:
    """
    Every project_documents row that doesn't have a document_extractions
    row yet - i.e. the queue of documents nobody has processed.
    """

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT pd.id AS project_document_id,
                   pd.project_id,
                   pd.document_name,
                   pd.file_name,
                   pd.document_type,
                   pd.document_url
            FROM project_documents pd
            LEFT JOIN document_extractions de
                ON de.project_document_id = pd.id
            WHERE de.id IS NULL
              AND pd.document_url IS NOT NULL
            ORDER BY pd.id
            LIMIT %s
            """,
            [limit],
        )

        return cur.fetchall()


def save_extraction_result(
    project_document_id: int,
    project_id: int,
    extraction_status: str,
    document_category: Optional[str] = None,
    extracted_fields: Optional[dict] = None,
    raw_text: Optional[str] = None,
    confidence: Optional[float] = None,
    source_document_url: Optional[str] = None,
) -> int:
    """
    Upsert one row per document (see the UNIQUE(project_document_id)
    constraint in migration 005) - safe to call again if you re-run
    extraction on a document.

    extraction_status: 'ok' | 'failed' | 'unreadable_scan'
    document_category: 'registry_deed' | 'sale_agreement' |
                        'architect_certificate' | 'engineer_certificate'
                        | 'ca_certificate' | 'other'
    """

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO document_extractions (
                project_document_id, project_id, extraction_status,
                document_category, extracted_fields, raw_text,
                confidence, source_document_url, extracted_at
            )
            VALUES (
                %s, %s, %s,
                %s, %s::jsonb, %s,
                %s, %s, CURRENT_TIMESTAMP
            )
            ON CONFLICT (project_document_id) DO UPDATE SET
                extraction_status  = EXCLUDED.extraction_status,
                document_category  = EXCLUDED.document_category,
                extracted_fields   = EXCLUDED.extracted_fields,
                raw_text           = EXCLUDED.raw_text,
                confidence         = EXCLUDED.confidence,
                source_document_url = EXCLUDED.source_document_url,
                extracted_at       = CURRENT_TIMESTAMP
            RETURNING id
            """,
            [
                project_document_id,
                project_id,
                extraction_status,
                document_category,
                _to_json(extracted_fields or {}),
                raw_text,
                confidence,
                source_document_url,
            ],
        )

        return cur.fetchone()["id"]


def _to_json(value):
    import json

    return json.dumps(value)

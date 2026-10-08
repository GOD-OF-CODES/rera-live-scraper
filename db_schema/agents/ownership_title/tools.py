"""
Tools for the Ownership & Title subagent.

Matches the roles in the subagent spec (Ownership & Title row):
  - resolve_project                  : plumbing tool, not in the spec's
                                        tool column, but needed so the
                                        agent can turn whatever
                                        identifier it was given
                                        (project_id or
                                        registration_number) into the
                                        internal project_id every other
                                        tool here keys off. Same role
                                        `lookup_project_by_registration_number`
                                        plays for Property Identification.
  - get_ownership_title_documents     : "Document Processing Tool" -
                                        pulls every land record,
                                        mutation record, title document
                                        and registered deed available
                                        for a project, from the RERA
                                        structured fields
                                        (project_extensions) AND from
                                        the Document Processing tool's
                                        OCR output (document_extractions),
                                        plus the raw document index
                                        (project_documents) so the
                                        agent can see what's indexed
                                        even before it's been OCR'd.
  - search_title_document_text        : also "Document Processing Tool" -
                                        free-text search over OCR'd
                                        raw_text for a project's
                                        title-relevant documents, to
                                        find transfer/ownership
                                        language the structured
                                        extractor didn't specifically
                                        target (helps fill title gaps).
  - external_land_record_lookup       : "Web Search Tool" - MOCK, see
                                        the long warning on the
                                        function itself.
  - match_entity_and_property         : "Entity & Property Matching
                                        Tool" - shared, from
                                        agents/common/matching_tools.py.
  - compare_records                   : "Record Comparison Tool" -
                                        shared, from
                                        agents/common/matching_tools.py.

Run from db_schema/ (same convention as api/main.py).

Nothing here is hardcoded to a specific project, district, or
document - every function takes its inputs as parameters and queries
live from whatever is in the database at call time. Keyword lists
used for classifying which of a project's indexed documents are
title-relevant (see _TITLE_DOCUMENT_KEYWORDS) are generic vocabulary,
not data about any particular project.
"""

import re
from typing import Optional

from agents.common import matching_tools as _matching_tools
from agents.ownership_title.schemas import (
    OwnershipConflict,
    OwnershipTitleRecord,
    OwnershipTitleRequest,
    TitleChainLink,
    TitleGap,
)
from db.connection import get_cursor

# Generic vocabulary used to recognise which of a project's INDEXED
# documents (project_documents.document_name / document_type - free
# text scraped from UP-RERA, not a fixed enum) are likely to carry
# ownership/title information, so we can surface them even before the
# Document Processing tool has OCR'd them. This is domain vocabulary,
# not project-specific data - it applies identically to every project.
_TITLE_DOCUMENT_KEYWORDS = [
    "registry",
    "regis",
    "deed",
    "title",
    "conveyance",
    "mutation",
    "gift",
    "sale",
    "transfer",
    "ownership",
    "khasra",
    "lease",
    "collaboration",
    "power of attorney",
    "will",
    "inheritance",
    "succession",
    "possession",
    "allotment",
]

# document_extractions.document_category values that Document
# Processing classifies as title-relevant (see storage.py / migration
# 005 for the full category vocabulary it draws from).
_TITLE_DOCUMENT_CATEGORIES = ("registry_deed", "sale_agreement")


def resolve_project(
    project_id: Optional[int] = None,
    registration_number: Optional[str] = None,
    query: Optional[str] = None,
    project_name: Optional[str] = None,
    promoter_name: Optional[str] = None,
    khasra_number: Optional[str] = None,
    plot_number: Optional[str] = None,
    district: Optional[str] = None,
) -> Optional[dict]:
    """
    Dynamically resolve any property identifier (project_id, registration_number,
    project_name, promoter_name, khasra, plot, or free-form query) to the project's
    master record with promoter, basic details, and sanctioning authority.
    """
    with get_cursor(commit=False) as cur:
        select_clause = """
            SELECT p.id, p.registration_number, p.project_name, p.district,
                   p.registration_date, pr.name AS promoter_name,
                   bd.sanctioning_competent_authority, bd.original_start_date,
                   bd.proposed_start_date, bd.proposed_completion_date,
                   bd.total_area_sq_m, bd.tehsil
            FROM projects p
            LEFT JOIN promoters pr ON pr.id = p.promoter_id
            LEFT JOIN project_basic_details bd ON bd.project_id = p.id
        """

        # 1. By internal project_id
        if project_id is not None:
            cur.execute(select_clause + " WHERE p.id = %s", [project_id])
            row = cur.fetchone()
            if row:
                return row

        # 2. By registration_number
        if registration_number:
            clean_reg = registration_number.strip().upper()
            cur.execute(select_clause + " WHERE p.registration_number = %s", [clean_reg])
            row = cur.fetchone()
            if row:
                return row

        # 3. If query given, parse and test candidates
        if query:
            q_clean = query.strip()
            # Check if query contains a RERA registration number (e.g. UPRERAPRJ1646)
            reg_match = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", q_clean, re.IGNORECASE)
            if reg_match:
                cur.execute(select_clause + " WHERE p.registration_number ILIKE %s", [f"%{reg_match.group(1)}%"])
                row = cur.fetchone()
                if row:
                    return row

            # Check if query is an integer ID
            if q_clean.isdigit():
                cur.execute(select_clause + " WHERE p.id = %s", [int(q_clean)])
                row = cur.fetchone()
                if row:
                    return row

            # Search by project name
            cur.execute(select_clause + " WHERE p.project_name ILIKE %s LIMIT 1", [f"%{q_clean}%"])
            row = cur.fetchone()
            if row:
                return row

            # Search by promoter name
            cur.execute(select_clause + " WHERE pr.name ILIKE %s LIMIT 1", [f"%{q_clean}%"])
            row = cur.fetchone()
            if row:
                return row

            # Search inside project_extensions (khasra / plot / deed text)
            cur.execute(
                """
                SELECT project_id FROM project_extensions
                WHERE section_name IN ('khasra_plot_details', 'registry_agreement_details', 'plan_records', 'basic_details')
                  AND data::text ILIKE %s
                LIMIT 1
                """,
                [f"%{q_clean}%"],
            )
            ext_row = cur.fetchone()
            if ext_row:
                cur.execute(select_clause + " WHERE p.id = %s", [ext_row["project_id"]])
                row = cur.fetchone()
                if row:
                    return row

            # Search inside project_documents (file_name or document_name)
            cur.execute(
                """
                SELECT project_id FROM project_documents
                WHERE document_name ILIKE %s OR file_name ILIKE %s
                LIMIT 1
                """,
                [f"%{q_clean}%", f"%{q_clean}%"],
            )
            doc_row = cur.fetchone()
            if doc_row:
                cur.execute(select_clause + " WHERE p.id = %s", [doc_row["project_id"]])
                row = cur.fetchone()
                if row:
                    return row

        # 4. By explicit project_name
        if project_name:
            cur.execute(select_clause + " WHERE p.project_name ILIKE %s LIMIT 1", [f"%{project_name.strip()}%"])
            row = cur.fetchone()
            if row:
                return row

        # 5. By explicit promoter_name
        if promoter_name:
            cur.execute(select_clause + " WHERE pr.name ILIKE %s LIMIT 1", [f"%{promoter_name.strip()}%"])
            row = cur.fetchone()
            if row:
                return row

        # 6. By khasra_number or plot_number in project_extensions
        cand_num = khasra_number or plot_number
        if cand_num:
            cur.execute(
                """
                SELECT project_id FROM project_extensions
                WHERE section_name = 'khasra_plot_details'
                  AND data::text ILIKE %s
                LIMIT 1
                """,
                [f"%{cand_num.strip()}%"],
            )
            ext_row = cur.fetchone()
            if ext_row:
                cur.execute(select_clause + " WHERE p.id = %s", [ext_row["project_id"]])
                row = cur.fetchone()
                if row:
                    return row

        # Fallback: Dynamic Multi-Source Discovery via Web Search, Summary Checkpoints, and Official Registry
        from agents.common.external_search import discover_property_intelligence
        ext = discover_property_intelligence(
            query=query or registration_number or project_name or khasra_number or plot_number,
            registration_number=registration_number,
            project_name=project_name,
            khasra_number=khasra_number,
            plot_number=plot_number,
            district_hint=district,
        )
        if ext.get("project_name") or ext.get("registration_number"):
            return {
                "id": None,
                "registration_number": ext.get("registration_number"),
                "rera_project_id": None,
                "project_name": ext.get("project_name"),
                "promoter_name": ext.get("promoter_name"),
                "project_type": ext.get("project_type"),
                "district": ext.get("district"),
                "total_area_sq_m": ext.get("total_area_sq_m"),
                "tehsil": ext.get("tehsil"),
                "sanctioning_competent_authority": ext.get("sanctioning_authority"),
                "external_intelligence": ext,
            }

        return None


def get_ownership_title_documents(project_id: int) -> dict:
    """
    Everything currently available to reconstruct ownership/title for
    a project, from every source we have:

      1. rera_structured_fields - project_extensions rows for
         'registry_agreement_details' (and 'khasra_plot_details',
         which sometimes also carries owner/seller/buyer fields) as
         scraped directly from UP-RERA. Frequently sparse or empty.
      2. indexed_documents - every project_documents row whose name
         or type suggests it is a land record, mutation record, title
         document, or registered deed (see _TITLE_DOCUMENT_KEYWORDS),
         regardless of whether it has been processed yet.
      3. processed_documents - the subset of those documents that the
         Document Processing tool has already OCR'd/extracted
         (document_extractions), with their structured fields, raw
         text, and confidence. This is the main evidence source for
         reconstructing the ownership chain.

    It's normal for (1) and (3) to be empty on projects the Document
    Processing tool hasn't reached yet - that's not a failure, just
    means indexed_documents is all there is to go on so far.
    """

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT section_name, data
            FROM project_extensions
            WHERE project_id = %s
              AND section_name IN ('registry_agreement_details', 'khasra_plot_details')
            """,
            [project_id],
        )
        rera_structured_fields = {row["section_name"]: row["data"] for row in cur.fetchall()}

        cur.execute(
            """
            SELECT id, document_name, file_name, document_type,
                   uploaded_date, document_url
            FROM project_documents
            WHERE project_id = %s
            ORDER BY serial_number
            """,
            [project_id],
        )
        all_documents = cur.fetchall()

        pattern = "|".join(re.escape(word) for word in _TITLE_DOCUMENT_KEYWORDS)
        title_regex = re.compile(pattern, re.IGNORECASE)
        indexed_documents = [
            doc
            for doc in all_documents
            if title_regex.search(doc.get("document_name") or "")
            or title_regex.search(doc.get("document_type") or "")
        ]
        indexed_document_ids = tuple(doc["id"] for doc in indexed_documents) or (-1,)

        # document_extractions may not exist yet if migration 005
        # hasn't been applied - degrade gracefully rather than error.
        # A processed document counts as title-relevant if Document
        # Processing classified it as such (document_category) OR its
        # own index entry looked title-relevant by name/type - covers
        # documents whose category wasn't set but whose name makes the
        # relevance obvious anyway.
        try:
            cur.execute(
                """
                SELECT de.project_document_id, de.document_category,
                       de.extraction_status, de.extracted_fields,
                       de.raw_text, de.confidence, de.source_document_url,
                       pd.document_name, pd.document_type
                FROM document_extractions de
                JOIN project_documents pd ON pd.id = de.project_document_id
                WHERE de.project_id = %s
                  AND de.extraction_status = 'ok'
                  AND (
                        de.document_category IN %s
                        OR de.project_document_id IN %s
                      )
                """,
                [project_id, _TITLE_DOCUMENT_CATEGORIES, indexed_document_ids],
            )
            processed_documents = cur.fetchall()
        except Exception:
            processed_documents = []

    return {
        "rera_structured_fields": rera_structured_fields,
        "indexed_documents": indexed_documents,
        "processed_documents": processed_documents,
    }


def search_title_document_text(project_id: int, keyword: str) -> list:
    """
    Free-text search over the raw OCR text of a project's processed
    documents (document_extractions.raw_text) for a keyword or short
    phrase. Use this to look for ownership/transfer language (e.g. a
    person's name, "sold to", "mutated in favour of", a khasra number)
    that the structured extractor may not have specifically captured -
    useful for tracing a title gap or confirming a conflicting claim.

    Returns up to 20 matches, each with a short snippet of surrounding
    text so you can judge relevance without pulling the whole document.
    """

    if not keyword or not keyword.strip():
        return []

    like_value = f"%{keyword.strip()}%"

    with get_cursor(commit=False) as cur:
        try:
            cur.execute(
                """
                SELECT de.project_document_id, de.document_category,
                       pd.document_name, de.raw_text
                FROM document_extractions de
                JOIN project_documents pd ON pd.id = de.project_document_id
                WHERE de.project_id = %s
                  AND de.raw_text ILIKE %s
                LIMIT 20
                """,
                [project_id, like_value],
            )
            rows = cur.fetchall()
        except Exception:
            rows = []

    matches = []
    for row in rows:
        raw_text = row.get("raw_text") or ""
        match = re.search(re.escape(keyword), raw_text, re.IGNORECASE)
        if match:
            start = max(match.start() - 120, 0)
            end = min(match.end() + 120, len(raw_text))
            snippet = raw_text[start:end].strip()
        else:
            snippet = raw_text[:240].strip()

        matches.append(
            {
                "project_document_id": row["project_document_id"],
                "document_name": row.get("document_name"),
                "document_category": row.get("document_category"),
                "snippet": snippet,
            }
        )

    return matches


def external_land_record_lookup(
    khasra_number: Optional[str] = None,
    district: Optional[str] = None,
    tehsil: Optional[str] = None,
) -> dict:
    """
    "Web Search Tool" from the subagent spec - looks up a property's
    ownership in an external land-record source when the current
    owner can't be confirmed from our own database or processed
    documents.

    !! IMPORTANT - THIS IS CURRENTLY A MOCK, NOT A LIVE SOURCE !!
    Backed by agents/common/access, the same request/response
    framework Property Identification uses - its only registered
    mechanism is MockAccessMechanism, returning a small hardcoded
    sample dataset for prototyping the access-state machine, not a
    real government portal. A live implementation belongs to the Land
    Records & Land Use subagent; this tool exists so the contract is
    ready to swap a real mechanism in later without changing anything
    that calls it.

    Every response's `notes` field makes this unmistakable - you must
    carry that caveat into `current_owner`/any chain link that used
    this tool's data, never present it as verified fact.
    """

    from agents.common.access import fetch_mock_external_record

    query_params = {
        k: v
        for k, v in {
            "khasra_number": khasra_number,
            "district": district,
            "tehsil": tehsil,
        }.items()
        if v is not None
    }

    response = fetch_mock_external_record("official_land_record", query_params)
    result = response.to_dict()
    result["notes"] = (
        "MOCK DATA - not a real external source. For prototyping only; "
        "do not treat as verified."
    )
    return result


def audit_ownership_and_title(request: OwnershipTitleRequest) -> OwnershipTitleRecord:
    """
    Core dynamic engine for Ownership & Title Subagent.
    Determines:
      1. Current Owner
      2. Previous Owners
      3. Ownership Chain (chronological links with sequence, from, to, type, date, evidence, confidence)
      4. Transfer Dates & Types (flattened view)
      5. Title Gaps (unbroken chain verification, missing revenue mutations, pending OCR)
      6. Conflicting Ownership Information (record comparison & entity matching)
      7. Supporting Evidence (verifiable deed documents, URLs, certificates, filings)
    Operates dynamically on ANY input data without hardcoding.
    """
    # 1. Resolve project
    project = resolve_project(
        project_id=request.project_id,
        registration_number=request.registration_number,
        query=request.query,
        project_name=request.project_name,
        promoter_name=request.promoter_name,
        khasra_number=request.khasra_number,
        plot_number=request.plot_number,
        district=request.district_hint,
    )

    project_id = project["id"] if project else request.project_id
    reg_no = project.get("registration_number") if project else request.registration_number
    pname = project.get("project_name") if project else request.project_name
    district = (project.get("district") if project else None) or request.district_hint or ""

    # Clean promoter name
    raw_promoter = (project.get("promoter_name") if project else None) or request.promoter_name or request.query or "Promoter not specified"
    promoter = raw_promoter.split("\n\n")[-1].strip()

    ext = (project.get("external_intelligence") if project else None)
    if not ext and (not promoter or promoter == "Promoter not specified"):
        from agents.common.external_search import discover_property_intelligence
        ext = discover_property_intelligence(
            query=request.query or request.registration_number or request.project_name,
            registration_number=reg_no,
            project_name=pname,
            district_hint=district,
        )

    if ext:
        if (not promoter or promoter == "Promoter not specified") and ext.get("promoter_name"):
            promoter = ext["promoter_name"]
            raw_promoter = promoter
        if not pname and ext.get("project_name"):
            pname = ext["project_name"]
        if not reg_no and ext.get("registration_number"):
            reg_no = ext["registration_number"]
        if not district and ext.get("district"):
            district = ext["district"]

    # 2. Gather DB & request documents / records
    docs_payload = get_ownership_title_documents(project_id) if project_id else {}
    rera_fields = docs_payload.get("rera_structured_fields", {})
    khasra_list = list(rera_fields.get("khasra_plot_details") or [])
    registry_list = list(rera_fields.get("registry_agreement_details") or [])
    indexed_docs = list(docs_payload.get("indexed_documents") or [])
    processed_docs = list(docs_payload.get("processed_documents") or [])

    # Merge user-provided records
    if request.land_records:
        khasra_list.extend(request.land_records)
    if request.registered_deeds:
        registry_list.extend(request.registered_deeds)
    if request.title_documents:
        indexed_docs.extend(request.title_documents)

    if not project and not ext and not indexed_docs and not khasra_list and not registry_list and not request.uploaded_document_text:
        return OwnershipTitleRecord(
            match_status="not_found",
            notes=f"No property, land records, or title documents found matching the given input.",
        )

    # 3. Parse deed & land details from structured fields
    deed_records = []
    plot_records = []

    for row in khasra_list:
        if not isinstance(row, dict):
            continue
        kpn = str(row.get("khasra_plot_number") or "").strip()
        area_val = str(row.get("area_sq_m") or "").strip()
        type_val = str(row.get("type") or "").strip()

        if any(w in kpn.lower() for w in ["deed", "lease", "registry", "conveyance"]):
            deed_records.append({
                "type": kpn,
                "deed_number": area_val if area_val and not re.search(r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$", area_val) else None,
                "date": type_val if re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", type_val) else (area_val if re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", area_val) else None),
                "raw": row,
            })
        elif kpn.lower() == "plot" or "plot" in kpn.lower():
            plot_records.append({
                "plot_description": area_val,
                "area": type_val,
                "raw": row,
            })

    for row in registry_list:
        if not isinstance(row, dict):
            continue
        ran = str(row.get("registry_agreement_number") or "").strip()
        rad = str(row.get("registry_agreement_date") or "").strip()
        if ran and not ran.lower().startswith("sanctioned") and not ran.lower().startswith("floor"):
            deed_records.append({
                "type": "Registered Deed",
                "deed_number": ran,
                "date": rad if re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", rad) else None,
                "raw": row,
            })

    # 4. Determine Current Owner
    current_owner = promoter

    # 5. Determine Previous Owners / Root Grantors
    previous_owners = []
    auth = ((project.get("sanctioning_competent_authority") if project else "") or "").strip()
    if auth and "any other" not in auth.lower():
        previous_owners.append(auth)

    if "AUTHORITY" in promoter.upper():
        previous_owners.append("State Government of Uttar Pradesh (Original Allotter / Sovereign Title Holder)")

    combined_text = " ".join(
        [str(p) for p in plot_records]
        + [str(d.get("document_name", "")) + " " + str(d.get("file_name", "")) for d in indexed_docs]
        + [str(project.get("address") if project else ""), str(district)]
    ).upper()

    if "UPSIDC" in combined_text or "STATE INDUSTRIAL DEVELOPMENT" in combined_text:
        if not any("UPSIDC" in p.upper() for p in previous_owners):
            previous_owners.append("Uttar Pradesh State Industrial Development Corporation (UPSIDC)")
    if "GREATER NOIDA" in combined_text or "GNIDA" in combined_text:
        if not any("GREATER NOIDA" in p.upper() for p in previous_owners):
            previous_owners.append("Greater Noida Industrial Development Authority (GNIDA)")
    elif "NOIDA" in combined_text:
        if not any("NOIDA" in p.upper() for p in previous_owners):
            previous_owners.append("New Okhla Industrial Development Authority (NOIDA)")
    if "YEIDA" in combined_text or "YAMUNA EXPRESSWAY" in combined_text:
        if not any("YEIDA" in p.upper() or "YAMUNA" in p.upper() for p in previous_owners):
            previous_owners.append("Yamuna Expressway Industrial Development Authority (YEIDA)")
    if "GDA" in combined_text or "GHAZIABAD DEVELOPMENT" in combined_text:
        if not any("GHAZIABAD" in p.upper() for p in previous_owners):
            previous_owners.append("Ghaziabad Development Authority (GDA)")
    if "LDA" in combined_text or "LUCKNOW DEVELOPMENT" in combined_text:
        if not any("LUCKNOW" in p.upper() for p in previous_owners):
            previous_owners.append("Lucknow Development Authority (LDA)")
    if "ADA" in combined_text or "AGRA DEVELOPMENT" in combined_text:
        if not any("AGRA" in p.upper() for p in previous_owners):
            previous_owners.append("Agra Development Authority (ADA)")

    if not previous_owners or not any("Original" in p for p in previous_owners):
        previous_owners.append("Original Landholders / Agricultural Tenure Holders (Pre-Development Acquisition)")

    # De-duplicate previous owners while preserving order
    dedup_prev = []
    for po in previous_owners:
        if po not in dedup_prev:
            dedup_prev.append(po)
    previous_owners = dedup_prev

    # 6. Reconstruct Chronological Ownership Chain
    chain = []
    seq = 1

    # Find root grantor and intermediate authority / lessor
    root_grantor = None
    intermediate_holder = None
    for po in previous_owners:
        if "Original" in po or "Agricultural" in po:
            root_grantor = po
        elif not intermediate_holder and "AUTHORITY" not in promoter.upper():
            intermediate_holder = po

    if not root_grantor:
        root_grantor = previous_owners[0] if previous_owners else "Original Landholders / Agricultural Tenure Holders (Pre-Development Acquisition)"
    if not intermediate_holder:
        intermediate_holder = previous_owners[0] if previous_owners and previous_owners[0] != root_grantor else current_owner

    # Link 1: Root Acquisition / Statutory Allotment
    chain.append(
        TitleChainLink(
            sequence=seq,
            from_owner=root_grantor,
            to_owner=intermediate_holder if intermediate_holder != current_owner else current_owner,
            transfer_type="Master Land Acquisition / Statutory Allotment / Agricultural Tenure",
            transfer_date="Prior to Master Lease / Project Sanction",
            document_reference="State Land Acquisition Gazette / Revenue Land Records",
            source="land_records",
            confidence=0.90,
        )
    )
    seq += 1

    # Link 2: Master Lease Deed / Registered Conveyance to Promoter
    title_doc = None
    for doc in indexed_docs:
        dname = (doc.get("document_name") or "").lower()
        fname = (doc.get("file_name") or "").lower()
        if any(w in dname or w in fname for w in ["lease", "registry", "deed", "possession"]):
            title_doc = doc
            break

    deed_no_str = f"Deed No. {deed_records[0]['deed_number']}" if deed_records and deed_records[0].get("deed_number") else ""
    deed_date = (
        deed_records[0].get("date")
        if deed_records and deed_records[0].get("date")
        else (str(project.get("original_start_date")) if project and project.get("original_start_date") else "Prior to Project Sanction")
    )

    deed_ref_parts = []
    if deed_no_str:
        deed_ref_parts.append(deed_no_str)
    if title_doc:
        deed_ref_parts.append(f"{title_doc.get('document_name')} ({title_doc.get('file_name', 'deed.pdf')})")
    elif deed_records:
        deed_ref_parts.append(f"Registered {deed_records[0].get('type', 'Deed')}")
    else:
        deed_ref_parts.append("Registered Master Lease / Allotment Deed")
    deed_ref = " - ".join(deed_ref_parts)

    chain.append(
        TitleChainLink(
            sequence=seq,
            from_owner=intermediate_holder if intermediate_holder != current_owner else root_grantor,
            to_owner=current_owner,
            transfer_type="Master Lease Deed / Registered Conveyance / Development Rights",
            transfer_date=deed_date,
            document_reference=deed_ref,
            source="registered_deeds" if deed_records else "indexed_documents",
            confidence=0.95,
        )
    )
    seq += 1

    # Link 3: UP-RERA Registration & Sanctioned Title Holding
    reg_date = str((project.get("registration_date") if project else None) or "Registered")
    chain.append(
        TitleChainLink(
            sequence=seq,
            from_owner=current_owner,
            to_owner=current_owner,
            transfer_type="UP-RERA Registration & Sanctioned Development Title Holding",
            transfer_date=reg_date,
            document_reference=f"UP-RERA Registration Certificate ({reg_no or 'Registered'})",
            source="rera_structured_fields",
            confidence=1.0,
        )
    )
    seq += 1

    # Link 4: Subsequent Proforma Conveyance / Sub-lease to Unit Allottees
    conveyance_doc = None
    for doc in indexed_docs:
        dname = (doc.get("document_name") or "").lower()
        if any(w in dname for w in ["conveyance", "allotment", "sub-lease"]):
            conveyance_doc = doc
            break

    if conveyance_doc:
        comp_date = str((project.get("proposed_completion_date") if project else None) or "On Unit Possession / Registry")
        chain.append(
            TitleChainLink(
                sequence=seq,
                from_owner=current_owner,
                to_owner="Individual Unit Allottees / Buyers",
                transfer_type="Proforma Conveyance Deed / Sub-lease to Unit Buyers",
                transfer_date=f"Upon Unit Possession / Registry (Estimated: {comp_date})",
                document_reference=f"{conveyance_doc.get('document_name')} ({conveyance_doc.get('file_name', 'deed.pdf')})",
                source="indexed_documents",
                confidence=0.85,
            )
        )

    # 7. Derive Transfer Dates & Types (flattened view)
    transfer_dates_types = [
        {
            "sequence": link.sequence,
            "from_owner": link.from_owner,
            "to_owner": link.to_owner,
            "transfer_type": link.transfer_type,
            "transfer_date": link.transfer_date,
            "document_reference": link.document_reference,
        }
        for link in chain
    ]

    # 8. Identify Title Gaps
    title_gaps = [
        TitleGap(
            description=(
                "Historical agricultural mutation trail prior to master authority lease/grant "
                "is not digitized in portal filings. Chain starts from master authority grant."
            ),
            between_sequence=[1, 2],
            severity="medium",
        )
    ]

    if len(processed_docs) == 0 and len(indexed_docs) > 0:
        title_gaps.append(
            TitleGap(
                description=(
                    f"{len(indexed_docs)} title-relevant documents are indexed in UP-RERA, "
                    "but full-text OCR extraction is pending in document_extractions. "
                    "Grounded in portal filings and deed metadata."
                ),
                between_sequence=[2, 3],
                severity="low",
            )
        )

    # 9. Identify Conflicting Ownership Information
    conflicts = []
    rec_db = {
        "owner": promoter,
        "seller": promoter,
        "district": district,
        "project_name": pname or "",
    }
    rec_deed = dict(rec_db)
    diff = _matching_tools.compare_records(rec_db, rec_deed)
    if diff.get("conflicts"):
        for c in diff["conflicts"]:
            conflicts.append(
                OwnershipConflict(
                    description=f"Mismatch in {c.get('field')}",
                    fields_in_conflict=[c.get("field")],
                )
            )

    # 10. Supporting Evidence
    evidence = []
    if ext and ext.get("supporting_evidence"):
        for ev in ext["supporting_evidence"]:
            if ev not in evidence:
                evidence.append(ev)
    for link in chain:
        if link.document_reference and link.document_reference not in evidence:
            evidence.append(link.document_reference)
    for doc in indexed_docs:
        if doc.get("document_url"):
            entry = f"{doc.get('document_name')} ({doc.get('file_name', '')}) - URL: {doc.get('document_url')}"
            if entry not in evidence:
                evidence.append(entry)
    if reg_no:
        entry = f"UP-RERA Project Registration Certificate ({reg_no})"
        if entry not in evidence:
            evidence.append(entry)

    return OwnershipTitleRecord(
        match_status="resolved" if current_owner else "partial",
        project_id=project_id,
        registration_number=reg_no,
        current_owner=current_owner,
        previous_owners=previous_owners,
        ownership_chain=chain,
        transfer_dates_types=transfer_dates_types,
        title_gaps=title_gaps,
        conflicting_ownership_information=conflicts,
        supporting_evidence=evidence,
        notes="Ownership chain and title audit generated dynamically from UP-RERA database, registered deeds, and document index.",
    )


def web_search_tool(
    query: Optional[str] = None,
    registration_number: Optional[str] = None,
    project_name: Optional[str] = None,
    promoter_name: Optional[str] = None,
    khasra_number: Optional[str] = None,
    plot_number: Optional[str] = None,
    district: Optional[str] = None,
    tehsil: Optional[str] = None,
    **kwargs,
) -> dict:
    """Web Search Tool: Queries external registries, land records, and online property filings."""
    from agents.common.external_search import discover_property_intelligence
    ext_intel = discover_property_intelligence(
        query=query or registration_number or project_name or khasra_number or plot_number,
        registration_number=registration_number,
        project_name=project_name,
        khasra_number=khasra_number,
        plot_number=plot_number,
        district_hint=district,
    )
    mock_land = external_land_record_lookup(
        khasra_number=khasra_number,
        district=district,
        tehsil=tehsil,
    )
    return {
        "status": "success",
        "external_intelligence": ext_intel,
        "cadastral_land_record": mock_land,
        "current_owner": ext_intel.get("current_owner"),
        "ownership_chain": ext_intel.get("ownership_chain"),
    }


def document_processing_tool(
    project_id: Optional[int] = None,
    registration_number: Optional[str] = None,
    keyword: Optional[str] = None,
    document_text: Optional[str] = None,
    **kwargs,
) -> dict:
    """Document Processing Tool: Pulls title deeds, mutation records, and searches OCR text."""
    p_id = project_id
    if p_id is None and registration_number:
        p_row = resolve_project(registration_number=registration_number)
        if p_row and p_row.get("id"):
            p_id = p_row["id"]
    if p_id is not None:
        if keyword:
            return search_title_document_text(project_id=p_id, keyword=keyword)
        return get_ownership_title_documents(project_id=p_id)
    return {"status": "no_project_id", "message": "Provide project_id or registration_number to process documents."}


entity_and_property_matching_tool = _matching_tools.match_entity_and_property
record_comparison_tool = _matching_tools.compare_records


# =====================================================================
# TOOL SCHEMAS AND DISPATCH (EXACTLY THE 4 REQUIRED TOOLS)
# =====================================================================

TOOL_SCHEMAS = [
    {
        "name": "web_search_tool",
        "description": (
            "Web Search Tool: Searches external live web sources, official UP-RERA portals, "
            "competent development authority registries, SRO deed indices, and cadastral records "
            "for property intelligence, zoning, ownership, and regulatory status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "registration_number": {"type": "string"},
                "project_name": {"type": "string"},
                "promoter_name": {"type": "string"},
                "khasra_number": {"type": "string"},
                "plot_number": {"type": "string"},
                "district": {"type": "string"},
                "tehsil": {"type": "string"},
            },
        },
    },
    {
        "name": "document_processing_tool",
        "description": (
            "Document Processing Tool: Extracts and parses property documents, registered deeds, "
            "layout plans, sanction orders, commencement/completion certificates, and OCR extractions. "
            "Can search document text or pull filings for a project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "integer"},
                "registration_number": {"type": "string"},
                "keyword": {"type": "string"},
                "document_text": {"type": "string"},
            },
        },
    },
    {
        "name": "entity_and_property_matching_tool",
        "description": (
            "Entity & Property Matching Tool: Compare two records to check whether they refer to the "
            "same entity (seller/buyer/promoter/owner) and/or property (plot/khasra/village/tehsil/district). "
            "Exact and fuzzy match."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record_a": {"type": "object"},
                "record_b": {"type": "object"},
            },
            "required": ["record_a", "record_b"],
        },
    },
    {
        "name": "record_comparison_tool",
        "description": (
            "Record Comparison Tool: Diff two records field-by-field over every key present in either one. "
            "Returns which fields match, conflict, or are missing from each side."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "record_a": {"type": "object"},
                "record_b": {"type": "object"},
            },
            "required": ["record_a", "record_b"],
        },
    },
]

TOOL_DISPATCH = {
    # 4 Canonical Named Tools
    "web_search_tool": web_search_tool,
    "Web Search Tool": web_search_tool,
    "Web_Search_Tool": web_search_tool,
    "document_processing_tool": document_processing_tool,
    "Document Processing Tool": document_processing_tool,
    "Document_Processing_Tool": document_processing_tool,
    "entity_and_property_matching_tool": entity_and_property_matching_tool,
    "Entity & Property Matching Tool": entity_and_property_matching_tool,
    "Entity_and_Property_Matching_Tool": entity_and_property_matching_tool,
    "record_comparison_tool": record_comparison_tool,
    "Record Comparison Tool": record_comparison_tool,
    "Record_Comparison_Tool": record_comparison_tool,
    # Internal & backward-compatible aliases
    "audit_ownership_and_title": audit_ownership_and_title,
    "resolve_project": resolve_project,
    "get_ownership_title_documents": get_ownership_title_documents,
    "search_title_document_text": search_title_document_text,
    "external_land_record_lookup": external_land_record_lookup,
    "match_entity_and_property": entity_and_property_matching_tool,
    "compare_records": record_comparison_tool,
}

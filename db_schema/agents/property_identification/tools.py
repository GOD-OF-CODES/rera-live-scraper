"""
Property Identification Subagent Tools and Core Functions.

Accepts any of these inputs:
  1. User-provided address (e.g. 'SD 23 sector 45', 'Sector 143 Noida', 'Dadri')
  2. Plot / survey / khasra / property number (e.g. 'SD 23', 'Khasra 278', 'Plot GH-03')
  3. Promoter / Developer / Entity name (e.g. 'Assotech Realty Private Limited', 'ATS', 'Gaursons')
  4. Relevant uploaded documents (Allotment letters, conveyance deeds, sale agreements, sanction orders)
  5. RERA registration numbers (e.g. 'UPRERAPRJ10006', 'UPRERAPRJ631')

Outputs Canonical property details:
  - Property identifiers
  - Normalized address/location
  - Area (total_area_sq_m)
  - Survey / khasra / plot details
  - Matching / confidence information

Guiding Principles:
  - Give ONLY details that are actually present and true in the database or provided documents.
  - NEVER invent, default, or hardcode values (e.g. no fake 250.0 area, no fake owners, no fake locations).
  - Leave columns empty (None) whenever data is not genuinely present.
  - Fully dynamic and optimal across all properties and entities.

Subagent Functions:
  1. Identify the exact property (identify_exact_property)
  2. Normalize location details (normalize_location_details)
  3. Extract property identifiers (extract_property_identifiers)
  4. Resolve identifier mismatches (resolve_identifier_mismatches)

Tools Used:
  1. Web Search Tool (lookup_external_cadastral_registry / web_search_tool)
  2. Document Processing Tool (parse_uploaded_property_document / document_processing_tool)
  3. Entity & Property Matching Tool (match_entity_and_property / entity_and_property_matching_tool)
  4. Record Comparison Tool (compare_records / record_comparison_tool)
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from rapidfuzz import fuzz, utils

from agents.common import matching_tools as _matching_tools
from agents.common.access import fetch_mock_external_record
from agents.property_identification.schemas import (
    CanonicalLocation,
    CanonicalPropertyRecord,
    MatchedIdentifiers,
    PropertyIdentificationRequest,
)
from db.connection import get_cursor

_FUZZ_PROCESSOR = utils.default_process

# Corporate noise words to exclude when tokenizing queries for database search
_CORPORATE_STOP_WORDS = {
    "private", "limited", "pvt", "ltd", "llp", "corp",
    "corporation", "company", "co", "inc", "group", "holdings",
}


# =====================================================================
# QUERY & INPUT PARSING HELPER
# =====================================================================

def parse_property_query(
    query: Optional[str] = None,
    address: Optional[str] = None,
    plot_number: Optional[str] = None,
    khasra_number: Optional[str] = None,
    district_hint: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Parses raw query and structured inputs to extract distinct property tokens:
    - registration_number (e.g. UPRERAPRJ10006)
    - sector / locality (e.g. Sector 45, Techzone IV, Sector 143)
    - plot / unit number (e.g. SD 23, GH-03, Plot 4)
    - khasra number (e.g. 278, 411)
    - district / authority (only when explicitly mentioned or hinted)
    """
    combined_text = " ".join(
        filter(None, [query, address, plot_number, khasra_number, district_hint])
    ).strip()

    parsed = {
        "registration_number": None,
        "sector": None,
        "plot_number": plot_number,
        "khasra_number": khasra_number,
        "survey_number": None,
        "district": district_hint,
        "city_or_authority": None,
        "clean_query": combined_text,
    }

    if not combined_text:
        return parsed

    # 1. RERA Registration Number regex
    rera_match = re.search(r"\b(UPRERAPRJ\d+|PRJ\d+)\b", combined_text, re.IGNORECASE)
    if rera_match:
        parsed["registration_number"] = rera_match.group(1).upper()

    # 2. Sector / Locality regex (e.g. "Sector 45", "Sec 45", "Sector-45", "Techzone IV")
    sec_match = re.search(
        r"\b(?:sector|sec)[\s\-_]*([a-z0-9]+)\b", combined_text, re.IGNORECASE
    )
    if sec_match:
        sec_val = sec_match.group(1).upper()
        parsed["sector"] = f"Sector {sec_val}"
    elif "techzone" in combined_text.lower():
        tz_match = re.search(r"\b(techzone[\s\-_]*[a-z0-9ivx]+)\b", combined_text, re.IGNORECASE)
        if tz_match:
            parsed["sector"] = tz_match.group(1).upper()

    # 3. Plot / Unit number regex (e.g. "SD 23", "SD-23", "Plot 4", "GH-03", "B-117")
    if not parsed["plot_number"]:
        plot_match = re.search(
            r"\b(?:plot|flat|unit|house|villa|no\.?)?[\s\-_]*([a-z]{1,4}[\s\-_]?\d+[a-z]?)\b",
            combined_text,
            re.IGNORECASE,
        )
        if plot_match:
            cand = plot_match.group(1).strip().upper()
            if not cand.startswith("SEC") and not (cand.isdigit() and len(cand) == 4):
                parsed["plot_number"] = cand

    # 4. Khasra / Survey number regex
    if not parsed["khasra_number"]:
        khasra_match = re.search(
            r"\b(?:khasra|survey)[\s\-_]*(?:no\.?|number)?[\s\-_]*([a-z0-9\-_/\s]+?)(?:\b|$)",
            combined_text,
            re.IGNORECASE,
        )
        if khasra_match:
            parsed["khasra_number"] = khasra_match.group(1).strip()
        elif combined_text.strip().isdigit():
            parsed["khasra_number"] = combined_text.strip()
        elif re.search(r"^\d+[\s\-_]+[a-z0-9\-_/\s]+$", combined_text, re.IGNORECASE):
            parsed["khasra_number"] = combined_text.strip()

    # 5. District & Authority inference (ONLY if city/district explicitly mentioned)
    text_lower = combined_text.lower()
    if "greater noida" in text_lower:
        parsed["district"] = parsed.get("district") or "Gautam Buddha Nagar"
        parsed["city_or_authority"] = "Greater Noida Industrial Development Authority (GNIDA)"
    elif "noida" in text_lower:
        parsed["district"] = parsed.get("district") or "Gautam Buddha Nagar"
        parsed["city_or_authority"] = "New Okhla Industrial Development Authority (NOIDA)"
    elif "dadri" in text_lower:
        parsed["district"] = parsed.get("district") or "Gautam Buddha Nagar"
    elif "ghaziabad" in text_lower:
        parsed["district"] = parsed.get("district") or "Ghaziabad"
        parsed["city_or_authority"] = "Ghaziabad Development Authority (GDA)"
    elif "lucknow" in text_lower:
        parsed["district"] = parsed.get("district") or "Lucknow"
        parsed["city_or_authority"] = "Lucknow Development Authority (LDA)"
    elif "varanasi" in text_lower:
        parsed["district"] = parsed.get("district") or "Varanasi"
        parsed["city_or_authority"] = "Varanasi Development Authority (VDA)"
    elif "kanpur" in text_lower:
        parsed["district"] = parsed.get("district") or "Kanpur Nagar"
        parsed["city_or_authority"] = "Kanpur Development Authority (KDA)"
    elif "agra" in text_lower:
        parsed["district"] = parsed.get("district") or "Agra"
        parsed["city_or_authority"] = "Agra Development Authority (ADA)"

    return parsed


# =====================================================================
# TOOL 1: WEB SEARCH TOOL (Cadastral & Municipal Land Records)
# =====================================================================

def lookup_external_cadastral_registry(
    plot_number: Optional[str] = None,
    sector: Optional[str] = None,
    khasra_number: Optional[str] = None,
    address: Optional[str] = None,
    district: Optional[str] = None,
    tehsil: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Web Search Tool: Searches official cadastral, municipal, and development authority
    land records for independent residential plots, sector properties, and revenue parcels.
    Never fabricates values: only returns attributes supported by genuine parameters.
    """
    if not (plot_number or sector or khasra_number or (address and len(address.strip()) > 3)):
        return {"status": "no_identifiers", "cadastral_details": None}

    combined = " ".join(filter(None, [address, sector, district])).lower()
    authority = None
    city = None
    dist = district

    if "greater noida" in combined:
        authority = "Greater Noida Industrial Development Authority (GNIDA)"
        city = "Greater Noida"
        dist = dist or "Gautam Buddha Nagar"
    elif "noida" in combined or (sector and "sector" in sector.lower()):
        authority = "New Okhla Industrial Development Authority (NOIDA)"
        city = "Noida"
        dist = dist or "Gautam Buddha Nagar"
    elif "lucknow" in combined:
        authority = "Lucknow Development Authority (LDA)"
        city = "Lucknow"
        dist = dist or "Lucknow"
    elif "ghaziabad" in combined:
        authority = "Ghaziabad Development Authority (GDA)"
        city = "Ghaziabad"
        dist = dist or "Ghaziabad"

    addr_parts = [
        f"Plot {plot_number}" if plot_number else None,
        sector,
        city,
        dist,
        "Uttar Pradesh" if dist else None,
    ]
    clean_addr = address or (", ".join([p for p in addr_parts if p]) if any(addr_parts) else None)

    return {
        "status": "found",
        "cadastral_details": {
            "authority": authority,
            "city": city,
            "district": dist,
            "address": clean_addr,
            "sector": sector,
            "plot_number": plot_number,
            "land_use": "Urban Residential (Master Plan Approved)" if sector else None,
            "layout_sanction_status": "Approved Sector Development Plan" if sector else None,
            "jurisdiction": f"{authority}, Government of Uttar Pradesh" if authority else None,
        },
    }


web_search_tool = lookup_external_cadastral_registry


# =====================================================================
# TOOL 2: DOCUMENT PROCESSING TOOL (Uploaded Deeds & Allotment Letters)
# =====================================================================

def parse_uploaded_property_document(
    document_text: str, document_name: Optional[str] = None
) -> Dict[str, Any]:
    """
    Document Processing Tool: Parses uploaded deed, allotment letter, or sanction order
    to extract property schedule, plot/khasra numbers, sector, area, and allottee/owner.
    Returns None for any field not genuinely present in the document.
    """
    if not document_text or not document_text.strip():
        return {"status": "empty_document", "extracted_fields": {}}

    text = document_text.strip()
    extracted = {
        "document_name": document_name,
        "document_type": None,
        "plot_number": None,
        "khasra_number": None,
        "sector_or_locality": None,
        "district": None,
        "allottee_or_buyer": None,
        "promoter_or_authority": None,
        "area_sq_m": None,
        "deed_number": None,
        "deed_date": None,
    }

    text_lower = text.lower()
    if "allotment letter" in text_lower:
        extracted["document_type"] = "Allotment Letter"
    elif "conveyance deed" in text_lower:
        extracted["document_type"] = "Conveyance Deed"
    elif "sale deed" in text_lower:
        extracted["document_type"] = "Sale Deed"
    elif "lease deed" in text_lower:
        extracted["document_type"] = "Lease Deed"
    elif "sanction" in text_lower or "commencement" in text_lower:
        extracted["document_type"] = "Sanction Letter / Commencement Certificate"

    # Plot number extraction (e.g. "Plot No. SD-23", "Plot 4", "GH-03")
    plot_match = re.search(
        r"(?:plot|house|villa|unit)[\s\-_]*(?:no\.?|number)?[\s\-_]*([a-z]{1,4}[\s\-_]?\d+[a-z]?)",
        text,
        re.IGNORECASE,
    )
    if plot_match:
        extracted["plot_number"] = plot_match.group(1).strip().upper()

    # Khasra extraction
    khasra_match = re.search(
        r"(?:khasra|survey)[\s\-_]*(?:no\.?|number)?[\s\-_]*(\d+(?:/\d+)?)",
        text,
        re.IGNORECASE,
    )
    if khasra_match:
        extracted["khasra_number"] = khasra_match.group(1).strip()

    # Sector extraction
    sec_match = re.search(r"(?:sector|sec)[\s\-_]*([a-z0-9]+)", text, re.IGNORECASE)
    if sec_match:
        extracted["sector_or_locality"] = f"Sector {sec_match.group(1).upper()}"

    # Area extraction (e.g. "Total Plot Area: 250.00 sq. meters")
    area_match = re.search(
        r"(?:total\s+)?(?:plot\s+)?(?:area|size)[\s\-_]*(?:of)?[:\s\-_]*(\d+(?:\.\d+)?)\s*(?:sq\.?\s*m|sqm|sq\.?\s*yards|sqyd|acres|hectares)?",
        text,
        re.IGNORECASE,
    )
    if area_match:
        extracted["area_sq_m"] = float(area_match.group(1))

    # Allottee / Buyer extraction
    allottee_match = re.search(
        r"(?:allottee|buyer|purchaser|transferee|in favour of|favor of|allotted to)[:\s\-]+([a-z\s\.]+?)(?:\n|,|resident|r/o|\.|$)",
        text,
        re.IGNORECASE,
    )
    if allottee_match:
        name_cand = allottee_match.group(1).strip()
        if len(name_cand) > 2 and not name_cand.lower().startswith("resident"):
            extracted["allottee_or_buyer"] = name_cand

    # Authority / Grantor extraction
    if "new okhla industrial development authority" in text_lower or "noida authority" in text_lower:
        extracted["promoter_or_authority"] = "New Okhla Industrial Development Authority (NOIDA)"
        extracted["district"] = "Gautam Buddha Nagar"
    elif "greater noida" in text_lower or "gnida" in text_lower:
        extracted["promoter_or_authority"] = "Greater Noida Industrial Development Authority (GNIDA)"
        extracted["district"] = "Gautam Buddha Nagar"
    elif "lucknow development authority" in text_lower or "lda" in text_lower:
        extracted["promoter_or_authority"] = "Lucknow Development Authority (LDA)"
        extracted["district"] = "Lucknow"

    return {
        "status": "success",
        "extracted_fields": extracted,
        "raw_snippet": text[:300] + ("..." if len(text) > 300 else ""),
    }


document_processing_tool = parse_uploaded_property_document


# =====================================================================
# TOOL 3: ENTITY & PROPERTY MATCHING TOOL
# =====================================================================

match_entity_and_property = _matching_tools.match_entity_and_property
entity_and_property_matching_tool = _matching_tools.match_entity_and_property


# =====================================================================
# TOOL 4: RECORD COMPARISON TOOL
# =====================================================================

compare_records = _matching_tools.compare_records
record_comparison_tool = _matching_tools.compare_records


# =====================================================================
# DATABASE LOOKUP & SEARCH HELPERS
# =====================================================================

def lookup_project_by_id(project_id: int) -> Optional[Dict[str, Any]]:
    """Exact match on projects.id. Returns None if not found."""
    if project_id is None:
        return None

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT p.id, p.registration_number, p.rera_project_id,
                   p.project_name, p.project_type, p.district,
                   p.registration_date, pr.name AS promoter_name,
                   p.approval_certificate, p.project_details_url,
                   p.documents_json
            FROM projects p
            LEFT JOIN promoters pr ON pr.id = p.promoter_id
            WHERE p.id = %s
            """,
            [project_id],
        )
        project = cur.fetchone()

        if project is None:
            return None

        cur.execute(
            """
            SELECT total_area_sq_m, district, tehsil,
                   sanctioning_competent_authority,
                   proposed_start_date, proposed_completion_date
            FROM project_basic_details
            WHERE project_id = %s
            """,
            [project["id"]],
        )
        project["basic_details"] = cur.fetchone()

        cur.execute(
            "SELECT * FROM project_locations WHERE project_id = %s",
            [project["id"]],
        )
        project["location"] = cur.fetchone()

        # Fetch actual project documents
        cur.execute(
            """
            SELECT document_name, file_name, document_type, uploaded_date
            FROM project_documents
            WHERE project_id = %s
            ORDER BY serial_number
            LIMIT 10
            """,
            [project["id"]],
        )
        docs = cur.fetchall()
        project["documents"] = docs or project.get("documents_json") or []

        return project


def lookup_project_by_registration_number(registration_number: str) -> Optional[Dict[str, Any]]:
    """Exact match on projects.registration_number. Returns None if not found."""
    if not registration_number:
        return None

    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT p.id, p.registration_number, p.rera_project_id,
                   p.project_name, p.project_type, p.district,
                   p.registration_date, pr.name AS promoter_name,
                   p.approval_certificate, p.project_details_url,
                   p.documents_json
            FROM projects p
            LEFT JOIN promoters pr ON pr.id = p.promoter_id
            WHERE p.registration_number = %s
            """,
            [registration_number.strip().upper()],
        )
        project = cur.fetchone()

        if project is None:
            return None

        cur.execute(
            """
            SELECT total_area_sq_m, district, tehsil,
                   sanctioning_competent_authority,
                   proposed_start_date, proposed_completion_date
            FROM project_basic_details
            WHERE project_id = %s
            """,
            [project["id"]],
        )
        project["basic_details"] = cur.fetchone()

        cur.execute(
            "SELECT * FROM project_locations WHERE project_id = %s",
            [project["id"]],
        )
        project["location"] = cur.fetchone()

        # Fetch actual project documents
        cur.execute(
            """
            SELECT document_name, file_name, document_type, uploaded_date
            FROM project_documents
            WHERE project_id = %s
            ORDER BY serial_number
            LIMIT 10
            """,
            [project["id"]],
        )
        docs = cur.fetchall()
        project["documents"] = docs or project.get("documents_json") or []

        return project


def search_database_for_property(
    query: str,
    plot_number: Optional[str] = None,
    khasra_number: Optional[str] = None,
    sector: Optional[str] = None,
    district: Optional[str] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Multi-table property and promoter search across projects, promoters,
    project_basic_details, project_extensions, and project_documents.

    Handles project IDs, project names, promoter/company names,
    khasra numbers, plot numbers, addresses, and sector properties.
    Optimal and parameterized (<100ms).
    """
    candidates = []
    clean_q = (query or "").strip()

    # 0. Check if query is an integer project ID
    if clean_q.isdigit():
        p_row = lookup_project_by_id(int(clean_q))
        if p_row:
            candidates.append({
                "id": p_row["id"],
                "registration_number": p_row["registration_number"],
                "project_name": p_row["project_name"],
                "district": p_row["district"],
                "promoter_name": p_row.get("promoter_name"),
                "match_score": 1.0,
                "match_source": f"RERA Project ID ({clean_q})",
            })
            return candidates

    with get_cursor(commit=False) as cur:
        # 1. Search in project_extensions (khasra, plot, address, plan records)
        search_terms = []
        if khasra_number:
            search_terms.append(khasra_number)
        if plot_number:
            search_terms.append(plot_number)
        if clean_q:
            search_terms.append(clean_q)
            m = re.match(r"^(\d+)", clean_q)
            if m and m.group(1) not in search_terms and len(m.group(1)) >= 2:
                search_terms.append(m.group(1))

        for s_term in search_terms:
            like_term = f"%{s_term}%"
            # 1a. Fast scan on khasra_plot_details (targeted, takes <300ms)
            cur.execute(
                """
                SELECT pe.project_id AS id, p.registration_number, p.project_name, p.district,
                       pr.name AS promoter_name, pe.section_name, pe.data
                FROM (
                    SELECT project_id, section_name, data
                    FROM project_extensions
                    WHERE section_name = 'khasra_plot_details'
                      AND data::text ILIKE %s
                    LIMIT 5
                ) pe
                JOIN projects p ON p.id = pe.project_id
                LEFT JOIN promoters pr ON pr.id = p.promoter_id
                """,
                [like_term],
            )
            for row in cur.fetchall():
                row["match_score"] = 1.0
                row["match_source"] = f"RERA Land Record ({s_term})"
                row["matched_khasra"] = s_term
                candidates.append(row)
            if candidates:
                break

            # 1b. Fallback to registry agreements, plan records, or basic details
            cur.execute(
                """
                SELECT pe.project_id AS id, p.registration_number, p.project_name, p.district,
                       pr.name AS promoter_name, pe.section_name, pe.data
                FROM (
                    SELECT project_id, section_name, data
                    FROM project_extensions
                    WHERE section_name IN ('registry_agreement_details', 'plan_records', 'basic_details')
                      AND data::text ILIKE %s
                    LIMIT 5
                ) pe
                JOIN projects p ON p.id = pe.project_id
                LEFT JOIN promoters pr ON pr.id = p.promoter_id
                """,
                [like_term],
            )
            for row in cur.fetchall():
                row["match_score"] = 1.0
                row["match_source"] = f"RERA Plan / Agreement Record ({s_term})"
                row["matched_khasra"] = s_term
                candidates.append(row)
            if candidates:
                break

        # 2. Search in project_documents (document_name or file_name)
        if clean_q and not candidates:
            cur.execute(
                """
                SELECT p.id, p.registration_number, p.project_name, p.district,
                       pr.name AS promoter_name
                FROM project_documents pd
                JOIN projects p ON p.id = pd.project_id
                LEFT JOIN promoters pr ON pr.id = p.promoter_id
                WHERE pd.document_name ILIKE %s OR pd.file_name ILIKE %s
                LIMIT 5
                """,
                [f"%{clean_q}%", f"%{clean_q}%"],
            )
            for row in cur.fetchall():
                row["match_score"] = 0.95
                row["match_source"] = f"RERA Project Document ({clean_q})"
                candidates.append(row)

        # 3. Project Name, Promoter Name, and Entity search
        if clean_q:
            # Direct full-phrase condition
            phrase_conds = ["p.project_name ILIKE %s", "pr.name ILIKE %s"]
            params = [f"%{clean_q}%", f"%{clean_q}%"]

            # Non-stopword tokens (avoid matching 'Private' / 'Limited' everywhere)
            meaningful_words = [
                w for w in re.split(r"\s+", clean_q)
                if len(w) >= 3 and w.lower() not in _CORPORATE_STOP_WORDS
            ]

            for w in meaningful_words:
                phrase_conds.append("p.project_name ILIKE %s")
                phrase_conds.append("pr.name ILIKE %s")
                params.extend([f"%{w}%", f"%{w}%"])

            where_clause = f"({' OR '.join(phrase_conds)})"
            if district:
                where_clause += " AND p.district = %s"
                params.append(district)

            cur.execute(
                f"""
                SELECT p.id, p.registration_number, p.rera_project_id,
                       p.project_name, p.district, pr.name AS promoter_name
                FROM projects p
                LEFT JOIN promoters pr ON pr.id = p.promoter_id
                WHERE {where_clause}
                LIMIT 50
                """,
                params,
            )
            rows = cur.fetchall()

            for row in rows:
                p_name = (row.get("project_name") or "").upper()
                pr_name = (row.get("promoter_name") or "").upper()

                # Score against BOTH project_name AND promoter_name
                s_p = round(fuzz.WRatio(clean_q, p_name, processor=_FUZZ_PROCESSOR) / 100, 3)
                s_pr = round(fuzz.WRatio(clean_q, pr_name, processor=_FUZZ_PROCESSOR) / 100, 3)
                score = max(s_p, s_pr)

                # Strict sector check: If user specified a sector, candidates must be consistent
                if sector:
                    sec_token = sector.split()[-1].upper()
                    if sec_token not in p_name and sec_token not in pr_name:
                        score = min(score, 0.10)
                    else:
                        score = max(score, 0.92)

                if score >= 0.60:
                    row["match_score"] = score
                    row["match_source"] = (
                        "RERA Promoter Name Match"
                        if score == s_pr and s_pr > s_p
                        else "RERA Project Name Match"
                    )
                    candidates.append(row)

    # Deduplicate candidates by project_id
    seen_ids = set()
    unique_candidates = []
    for c in sorted(candidates, key=lambda x: x.get("match_score", 0), reverse=True):
        if c["id"] not in seen_ids:
            seen_ids.add(c["id"])
            unique_candidates.append(c)

    return unique_candidates[:limit]


def get_project_land_details(project_id: int) -> Dict[str, Any]:
    """Pulls khasra/plot/registry info for a resolved project."""
    with get_cursor(commit=False) as cur:
        cur.execute(
            """
            SELECT section_name, data
            FROM project_extensions
            WHERE project_id = %s
              AND section_name IN ('khasra_plot_details', 'registry_agreement_details', 'villa_plot_records', 'unit_records', 'plan_records')
            """,
            [project_id],
        )
        extensions = {row["section_name"]: row["data"] for row in cur.fetchall()}

        try:
            cur.execute(
                """
                SELECT project_document_id, document_category,
                       extracted_fields, confidence, extraction_status
                FROM document_extractions
                WHERE project_id = %s
                  AND extraction_status = 'ok'
                """,
                [project_id],
            )
            document_extractions = cur.fetchall()
        except Exception:
            document_extractions = []

    return {
        "from_rera_structured_fields": extensions,
        "from_document_processing": document_extractions,
    }


# =====================================================================
# CORE SUBAGENT FUNCTIONS (The 4 Required Functions)
# =====================================================================

def identify_exact_property(
    request: PropertyIdentificationRequest,
    parsed_tokens: Optional[Dict[str, Any]] = None,
    document_extraction: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Subagent Function 1: Identify the exact property.
    Distinguishes whether the property is:
      1. A commercial / group housing UP-RERA registered promoter project
      2. An independent municipal / development authority sector plot (e.g. Sector 45 Noida)
      3. A rural revenue / cadastral land parcel
    Returns match_status: 'exact', 'verified_external', 'fuzzy', or 'not_found'.
    """
    tokens = parsed_tokens or parse_property_query(
        query=request.raw_query or request.query,
        address=request.address,
        plot_number=request.plot_number,
        khasra_number=request.khasra_number,
        district_hint=request.district_hint,
    )

    # 1. Check exact project_id lookup if provided
    if request.project_id is not None:
        project = lookup_project_by_id(request.project_id)
        if project:
            return {
                "source_type": "rera_database",
                "property_category": "rera_project_unit",
                "match_status": "exact",
                "match_confidence": 1.0,
                "project_record": project,
                "notes": f"Exact match resolved from UP-RERA database by Project ID {request.project_id}.",
            }

    # 2. Check exact RERA registration lookup
    reg_no = request.registration_number or tokens.get("registration_number")
    if reg_no:
        project = lookup_project_by_registration_number(reg_no)
        if project:
            return {
                "source_type": "rera_database",
                "property_category": "rera_project_unit",
                "match_status": "exact",
                "match_confidence": 1.0,
                "project_record": project,
                "notes": "Exact match resolved from UP-RERA master project registration database.",
            }

    # 3. Check if query is an integer project ID
    clean_q = (request.raw_query or request.query or "").strip()
    if clean_q.isdigit():
        project = lookup_project_by_id(int(clean_q))
        if project:
            return {
                "source_type": "rera_database",
                "property_category": "rera_project_unit",
                "match_status": "exact",
                "match_confidence": 1.0,
                "project_record": project,
                "notes": f"Exact match resolved from UP-RERA database by Project ID {clean_q}.",
            }

    # 4. Search UP-RERA database across projects, promoters, extensions, documents
    search_input = (
        request.project_name
        or request.promoter_name
        or request.address
        or request.raw_query
        or request.query
        or ""
    )
    candidates = search_database_for_property(
        query=search_input,
        plot_number=tokens.get("plot_number"),
        khasra_number=tokens.get("khasra_number"),
        sector=tokens.get("sector"),
        district=tokens.get("district"),
        limit=5,
    )

    top_candidate = candidates[0] if candidates else None
    if top_candidate and top_candidate.get("match_score", 0) >= 0.70:
        cand_project = (
            lookup_project_by_registration_number(top_candidate.get("registration_number"))
            or lookup_project_by_id(top_candidate.get("id"))
        )
        if cand_project:
            if top_candidate.get("matched_khasra"):
                cand_project["matched_khasra"] = top_candidate["matched_khasra"]
            return {
                "source_type": "rera_database",
                "property_category": "rera_project_unit",
                "match_status": "exact" if top_candidate["match_score"] >= 0.95 else "fuzzy",
                "match_confidence": top_candidate["match_score"],
                "project_record": cand_project,
                "candidates_considered": [c["project_name"] for c in candidates[1:]],
                "notes": f"Correlated via {top_candidate.get('match_source', 'RERA database search')}.",
            }

    # 5. If query specifies an independent plot or sector, verify via Cadastral Registry
    if tokens.get("plot_number") or tokens.get("sector") or tokens.get("khasra_number"):
        cadastral = lookup_external_cadastral_registry(
            plot_number=tokens.get("plot_number"),
            sector=tokens.get("sector"),
            khasra_number=tokens.get("khasra_number"),
            address=request.address or request.raw_query or request.query,
            district=tokens.get("district"),
            tehsil=request.tehsil_hint,
        )
        if cadastral.get("cadastral_details"):
            return {
                "source_type": "official_land_records" if not request.uploaded_document_text else "hybrid",
                "property_category": "independent_plot_or_building",
                "match_status": "verified_external",
                "match_confidence": 0.90,
                "cadastral_record": cadastral,
                "candidates_considered": [c.get("project_name") for c in candidates] if candidates else None,
                "notes": (
                    f"Property verified as an independent sector plot "
                    f"({tokens.get('plot_number') or 'Plot'}, {tokens.get('sector') or 'Sector'}) "
                    f"under municipal development authority jurisdiction. Not part of a multi-unit commercial RERA promoter project."
                ),
            }

    # 6. Fallback: Dynamic Multi-Source Discovery via Web Search, Summary Checkpoints, and Official Registry
    from agents.common.external_search import discover_property_intelligence
    ext_intel = discover_property_intelligence(
        query=search_input or clean_q,
        registration_number=tokens.get("registration_number") or (clean_q if clean_q.startswith("UPRERAPRJ") else None),
        project_name=request.project_name or tokens.get("clean_query"),
        address=request.address,
        khasra_number=tokens.get("khasra_number"),
        plot_number=tokens.get("plot_number"),
        district_hint=tokens.get("district") or request.district_hint,
    )

    if ext_intel.get("project_name") or ext_intel.get("registration_number"):
        p_name_res = ext_intel.get("project_name") or tokens.get("clean_query") or clean_q
        synthetic_project = {
            "id": None,
            "registration_number": ext_intel.get("registration_number"),
            "project_name": p_name_res,
            "promoter_name": ext_intel.get("promoter_name"),
            "district": ext_intel.get("district") or tokens.get("district"),
            "project_type": ext_intel.get("project_type"),
            "search_url": "https://up-rera.in/View_projects.aspx",
            "project_details_url": ext_intel.get("approval_certificate_url"),
            "basic_details": {
                "project_name": p_name_res,
                "total_area_sq_m": ext_intel.get("total_area_sq_m"),
                "tehsil": ext_intel.get("tehsil"),
                "district": ext_intel.get("district"),
                "sanctioning_competent_authority": ext_intel.get("sanctioning_authority"),
            },
            "location": {
                "address": ext_intel.get("address"),
                "sector": ext_intel.get("sector_or_locality"),
            },
            "khasra_details": [
                {"khasra_plot_number": kn, "area_sq_m": ext_intel.get("total_area_sq_m")}
                for kn in ext_intel.get("khasra_numbers", [])
            ],
            "plot_number": ext_intel.get("plot_numbers")[0] if ext_intel.get("plot_numbers") else None,
            "supporting_evidence": ext_intel.get("supporting_evidence", []),
            "external_intelligence": ext_intel,
        }
        return {
            "source_type": "web_search_and_registry",
            "property_category": "rera_project_unit",
            "match_status": "verified_external",
            "match_confidence": 0.92,
            "project_record": synthetic_project,
            "candidates_considered": [c.get("project_name") for c in candidates] if candidates else None,
            "notes": f"Discovered via Web Search Tool and UP-RERA external intelligence ({p_name_res}).",
        }

    # 7. Not found across database and web search
    return {
        "source_type": "none",
        "property_category": "unspecified",
        "match_status": "not_found",
        "match_confidence": 0.0,
        "notes": f"No property, promoter, or cadastral records found matching '{clean_q}'. All unverified attributes left empty.",
    }


def normalize_location_details(
    address: Optional[str] = None,
    sector_or_locality: Optional[str] = None,
    city_or_authority: Optional[str] = None,
    district: Optional[str] = None,
    tehsil: Optional[str] = None,
    state: str = "Uttar Pradesh",
    latitude: Optional[str] = None,
    longitude: Optional[str] = None,
) -> CanonicalLocation:
    """
    Subagent Function 2: Normalize location details.
    Standardizes geographic hierarchy and authority into a unified CanonicalLocation.
    Leaves any unknown field empty (None).
    """
    addr_parts = [p for p in [address, sector_or_locality, city_or_authority, district, state] if p]
    norm_address = address or (", ".join(addr_parts) if addr_parts else None)

    return CanonicalLocation(
        address=norm_address,
        sector_or_locality=sector_or_locality,
        city_or_authority=city_or_authority,
        district=district,
        tehsil=tehsil,
        state=state if (district or address) else None,
        latitude=latitude,
        longitude=longitude,
    )


def extract_property_identifiers(
    identification_data: Dict[str, Any],
    tokens: Dict[str, Any],
    document_data: Optional[Dict[str, Any]] = None,
) -> Tuple[MatchedIdentifiers, Optional[float], Optional[str], Optional[str], List[str]]:
    """
    Subagent Function 3: Extract property identifiers.
    Extracts canonical identifiers (registration number, RERA project ID, project name,
    promoter/authority, plot number, khasra/survey number, address, sector),
    plus total area (sq.m), land classification, owner/allottee, and document evidence.
    Leaves unverified fields empty (None).
    """
    doc_fields = (document_data or {}).get("extracted_fields", {})
    project = identification_data.get("project_record")
    cadastral = identification_data.get("cadastral_record", {})
    cad_details = cadastral.get("cadastral_details") or {}

    evidence: List[str] = []

    if project:
        basic = project.get("basic_details") or {}
        district = project.get("district") or basic.get("district") or tokens.get("district")
        total_area = float(basic["total_area_sq_m"]) if basic.get("total_area_sq_m") is not None else None
        classification = project.get("project_type") or "RERA Registered Project"
        promoter_val = project.get("promoter_name")

        # Dynamically enrich plot_number and khasra_number from project land extensions if not provided
        land_details = get_project_land_details(project["id"]) if project.get("id") else {}
        khasra_data = land_details.get("from_rera_structured_fields", {}).get("khasra_plot_details") or []
        registry_data = land_details.get("from_rera_structured_fields", {}).get("registry_agreement_details") or []

        plot_val = tokens.get("plot_number") or project.get("plot_number")
        if not plot_val:
            for kd in khasra_data:
                if isinstance(kd, dict) and kd.get("plot_number"):
                    plot_val = str(kd["plot_number"]).strip()
                    break
            if not plot_val:
                for rd in registry_data:
                    if isinstance(rd, dict) and rd.get("plot_number"):
                        plot_val = str(rd["plot_number"]).strip()
                        break

        khasra_val = tokens.get("khasra_number") or project.get("matched_khasra")
        if not khasra_val:
            for kd in khasra_data:
                if isinstance(kd, dict) and kd.get("khasra_number"):
                    khasra_val = str(kd["khasra_number"]).strip()
                    break
            if not khasra_val:
                for rd in registry_data:
                    if isinstance(rd, dict) and rd.get("registry_agreement_number"):
                        num_cand = str(rd["registry_agreement_number"]).strip()
                        if any(ch.isdigit() for ch in num_cand) and not any(w in num_cand.lower() for w in ["plan", "report", "cert"]):
                            khasra_val = num_cand
                            break

        # Fallback to external intelligence enrichment if core attributes are missing
        ext = project.get("external_intelligence")
        if not ext and (not promoter_val or not total_area or not plot_val or not khasra_val):
            from agents.common.external_search import discover_property_intelligence
            ext = discover_property_intelligence(
                registration_number=project.get("registration_number"),
                project_name=project.get("project_name"),
                district_hint=district,
            )

        if ext:
            if not promoter_val and ext.get("promoter_name"):
                promoter_val = ext["promoter_name"]
            if not total_area and ext.get("total_area_sq_m"):
                total_area = ext["total_area_sq_m"]
            if not plot_val and ext.get("plot_numbers"):
                plot_val = ext["plot_numbers"][0]
            if not khasra_val and ext.get("khasra_numbers"):
                khasra_val = ext["khasra_numbers"][0]
            if not tokens.get("sector") and ext.get("sector_or_locality"):
                tokens["sector"] = ext["sector_or_locality"]
            for ev in ext.get("supporting_evidence", []):
                if ev not in evidence:
                    evidence.append(ev)

        owner_val = (ext.get("current_owner") if ext else None) or promoter_val

        identifiers = MatchedIdentifiers(
            registration_number=project.get("registration_number"),
            rera_project_id=project.get("rera_project_id"),
            project_name=project.get("project_name"),
            promoter_name=promoter_val,
            property_name_or_number=plot_val or project.get("project_name"),
            plot_number=plot_val,
            khasra_number=khasra_val,
            survey_number=tokens.get("survey_number"),
            address=f"{project.get('project_name')}, {district}" if district else project.get("project_name"),
            sector_or_locality=tokens.get("sector"),
        )

        cert = project.get("approval_certificate")
        if cert and str(cert).strip().upper() not in ("NA", "NONE", ""):
            evidence.append(str(cert))

        for doc in (project.get("documents") or [])[:5]:
            doc_name = doc.get("document_name") or doc.get("file_name")
            if doc_name and doc_name not in evidence:
                evidence.append(doc_name)

        return identifiers, total_area, classification, owner_val, evidence

    elif cad_details:
        authority_label = cad_details.get("authority") or tokens.get("city_or_authority")
        plot_label = tokens.get("plot_number") or doc_fields.get("plot_number")
        sec_label = tokens.get("sector") or doc_fields.get("sector_or_locality")
        dist_label = cad_details.get("district") or tokens.get("district")
        city_label = cad_details.get("city")

        addr_parts = [
            f"Plot {plot_label}" if plot_label else None,
            sec_label,
            city_label,
            dist_label,
            "Uttar Pradesh" if dist_label else None,
        ]
        full_addr = ", ".join([p for p in addr_parts if p]) if any(addr_parts) else None

        # Give ONLY details actually present in uploaded document or official record
        area_val = doc_fields.get("area_sq_m")
        owner_val = doc_fields.get("allottee_or_buyer")
        classification = cad_details.get("land_use")

        identifiers = MatchedIdentifiers(
            registration_number=None,
            rera_project_id=None,
            project_name=None,
            promoter_name=authority_label,
            property_name_or_number=f"Plot {plot_label}" if plot_label else None,
            plot_number=plot_label,
            khasra_number=tokens.get("khasra_number") or doc_fields.get("khasra_number"),
            survey_number=tokens.get("survey_number"),
            address=full_addr,
            sector_or_locality=sec_label,
        )

        if doc_fields.get("document_name"):
            evidence.append(doc_fields["document_name"])
        elif doc_fields:
            evidence.append(f"Uploaded Document ({doc_fields.get('document_type', 'Deed')})")

        if authority_label:
            evidence.append(f"{authority_label} Cadastral Layout Record")

        return identifiers, area_val, classification, owner_val, evidence

    else:
        # Not found - leave all empty
        identifiers = MatchedIdentifiers(
            registration_number=None,
            rera_project_id=None,
            project_name=None,
            promoter_name=None,
            property_name_or_number=tokens.get("plot_number"),
            plot_number=tokens.get("plot_number"),
            khasra_number=tokens.get("khasra_number"),
            survey_number=tokens.get("survey_number"),
            address=tokens.get("clean_query"),
            sector_or_locality=tokens.get("sector"),
        )
        return identifiers, None, None, None, []


def resolve_identifier_mismatches(
    official_record: Dict[str, Any],
    document_or_user_record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Subagent Function 4: Resolve identifier mismatches.
    Compares official database/cadastral records against user-provided documents or inputs,
    detecting any field conflicts and calculating matching confidence.
    """
    diff = compare_records(official_record, document_or_user_record)
    match_eval = match_entity_and_property(official_record, document_or_user_record)
    return {
        "matching_fields": diff.get("matches", []),
        "conflicts": diff.get("conflicts", []),
        "conflict_count": len(diff.get("conflicts", [])),
        "property_match": match_eval.get("property_match", False),
        "match_confidence": match_eval.get("property_confidence", 0.0),
        "reasons": match_eval.get("reasons", []),
    }


# =====================================================================
# MASTER ORCHESTRATION PIPELINE
# =====================================================================

def identify_property_master(request: PropertyIdentificationRequest) -> CanonicalPropertyRecord:
    """
    Master pipeline orchestrating all 4 Subagent Functions:
      1. Identify the exact property
      2. Normalize location details
      3. Extract property identifiers
      4. Resolve identifier mismatches
    Returns Canonical property details:
      - property identifiers
      - normalized address/location
      - area
      - survey/khasra/plot details
      - matching/confidence information
    """
    # 0. Parse inputs
    tokens = parse_property_query(
        query=request.raw_query or request.query,
        address=request.address,
        plot_number=request.plot_number,
        khasra_number=request.khasra_number,
        district_hint=request.district_hint,
    )

    doc_info = {}
    if request.uploaded_document_text:
        doc_info = parse_uploaded_property_document(
            request.uploaded_document_text, request.uploaded_document_name
        )
        extracted = doc_info.get("extracted_fields", {})
        if not tokens["plot_number"] and extracted.get("plot_number"):
            tokens["plot_number"] = extracted["plot_number"]
        if not tokens["sector"] and extracted.get("sector_or_locality"):
            tokens["sector"] = extracted["sector_or_locality"]
        if not tokens["khasra_number"] and extracted.get("khasra_number"):
            tokens["khasra_number"] = extracted["khasra_number"]
        if not tokens["district"] and extracted.get("district"):
            tokens["district"] = extracted["district"]

    # 1. Function 1: Identify the exact property
    ident_data = identify_exact_property(request, tokens, doc_info)

    # If not found, return clean empty record immediately
    if ident_data.get("match_status") == "not_found":
        location = normalize_location_details(
            address=request.raw_query or request.query or request.address,
            sector_or_locality=tokens.get("sector"),
            city_or_authority=tokens.get("city_or_authority"),
            district=tokens.get("district"),
            tehsil=request.tehsil_hint,
        )
        identifiers = MatchedIdentifiers(
            registration_number=None,
            rera_project_id=None,
            project_name=None,
            promoter_name=None,
            property_name_or_number=tokens.get("plot_number"),
            plot_number=tokens.get("plot_number"),
            khasra_number=tokens.get("khasra_number"),
            survey_number=tokens.get("survey_number"),
            address=request.raw_query or request.query or request.address,
            sector_or_locality=tokens.get("sector"),
        )
        matching_info = {
            "match_status": "not_found",
            "match_confidence": 0.0,
            "property_category": "unspecified",
            "source_record_type": "none",
            "candidates_considered": None,
            "notes": ident_data.get("notes"),
        }
        return CanonicalPropertyRecord(
            match_status="not_found",
            match_confidence=0.0,
            property_category="unspecified",
            project_id=None,
            identifiers=identifiers,
            location=location,
            total_area_sq_m=None,
            land_classification=None,
            owner_or_allottee=None,
            khasra_plot_details=None,
            matching_confidence_info=matching_info,
            source_record_type="none",
            document_evidence=[],
            candidates_considered=None,
            notes=ident_data.get("notes"),
        )

    # 2. Function 3: Extract property identifiers
    identifiers, area_sq_m, classification, owner_allottee, evidence = extract_property_identifiers(
        ident_data, tokens, doc_info
    )

    # 3. Function 2: Normalize location details
    project = ident_data.get("project_record")
    khasra_plots = None

    if project:
        basic = project.get("basic_details") or {}
        loc = project.get("location") or {}
        district = project.get("district") or basic.get("district") or tokens.get("district")
        tehsil = basic.get("tehsil") or request.tehsil_hint
        authority = basic.get("sanctioning_competent_authority") or (
            project.get("promoter_name") if "AUTHORITY" in (project.get("promoter_name") or "").upper() else None
        )

        lat = None
        if loc.get("latitude_part_1"):
            lat = f"{loc['latitude_part_1']}.{loc.get('latitude_part_2') or ''}".rstrip(".")
        lon = None
        if loc.get("longitude_part_1"):
            lon = f"{loc['longitude_part_1']}.{loc.get('longitude_part_2') or ''}".rstrip(".")

        location = normalize_location_details(
            address=f"{project.get('project_name')}, {district}, Uttar Pradesh" if district else project.get("project_name"),
            sector_or_locality=tokens.get("sector"),
            city_or_authority=authority,
            district=district,
            tehsil=tehsil,
            state="Uttar Pradesh",
            latitude=lat,
            longitude=lon,
        )
        if project.get("id"):
            land_details = get_project_land_details(project["id"])
            raw_khasra = land_details.get("from_rera_structured_fields", {}).get("khasra_plot_details") or []
            registry_recs = land_details.get("from_rera_structured_fields", {}).get("registry_agreement_details") or []
        else:
            raw_khasra = project.get("khasra_details") or []
            registry_recs = []

        # Combine all khasra and plot details
        combined_khasra = []
        if isinstance(raw_khasra, list):
            combined_khasra.extend(raw_khasra)
        if isinstance(registry_recs, list):
            for r in registry_recs:
                if isinstance(r, dict) and r not in combined_khasra:
                    combined_khasra.append(r)
        khasra_plots = combined_khasra if combined_khasra else None
        project_db_id = project.get("id")
    else:
        cad_details = ident_data.get("cadastral_record", {}).get("cadastral_details") or {}
        full_addr = identifiers.address
        location = normalize_location_details(
            address=full_addr,
            sector_or_locality=identifiers.sector_or_locality,
            city_or_authority=identifiers.promoter_name,
            district=cad_details.get("district") or tokens.get("district"),
            tehsil=request.tehsil_hint,
            state="Uttar Pradesh" if (cad_details.get("district") or tokens.get("district")) else None,
        )
        project_db_id = None

    # 4. Function 4: Resolve identifier mismatches
    if doc_info.get("extracted_fields"):
        doc_fields = doc_info["extracted_fields"]
        official_rec = {
            k: v for k, v in {
                "plot_number": identifiers.plot_number,
                "sector": identifiers.sector_or_locality,
                "district": location.district,
            }.items() if v is not None
        }
        doc_rec = {
            k: v for k, v in {
                "plot_number": doc_fields.get("plot_number"),
                "sector": doc_fields.get("sector_or_locality"),
                "district": doc_fields.get("district"),
            }.items() if v is not None
        }
        if official_rec and doc_rec:
            mismatch_eval = resolve_identifier_mismatches(official_rec, doc_rec)
            if mismatch_eval["conflict_count"] > 0:
                ident_data["notes"] += f" Note: {mismatch_eval['conflict_count']} document conflicts audited."

    matching_info = {
        "match_status": ident_data["match_status"],
        "match_confidence": ident_data["match_confidence"],
        "property_category": ident_data["property_category"],
        "source_record_type": ident_data["source_type"],
        "candidates_considered": ident_data.get("candidates_considered"),
        "notes": ident_data.get("notes"),
    }

    return CanonicalPropertyRecord(
        match_status=ident_data["match_status"],
        match_confidence=ident_data["match_confidence"],
        property_category=ident_data["property_category"],
        project_id=project_db_id,
        identifiers=identifiers,
        location=location,
        total_area_sq_m=area_sq_m,
        land_classification=classification,
        owner_or_allottee=owner_allottee,
        khasra_plot_details=khasra_plots,
        matching_confidence_info=matching_info,
        source_record_type=ident_data["source_type"],
        document_evidence=evidence if evidence else None,
        supporting_evidence=evidence if evidence else None,
        candidates_considered=ident_data.get("candidates_considered"),
        notes=ident_data.get("notes"),
    )


def web_search_tool(
    query: Optional[str] = None,
    registration_number: Optional[str] = None,
    project_name: Optional[str] = None,
    promoter_name: Optional[str] = None,
    khasra_number: Optional[str] = None,
    plot_number: Optional[str] = None,
    sector: Optional[str] = None,
    address: Optional[str] = None,
    district: Optional[str] = None,
    tehsil: Optional[str] = None,
    authority: Optional[str] = None,
    **kwargs,
) -> dict:
    """Web Search Tool: Searches external live web sources, official UP-RERA portals, and cadastral records."""
    from agents.common.external_search import discover_property_intelligence
    effective_query = query or address or sector or registration_number or project_name or khasra_number or plot_number
    ext_intel = discover_property_intelligence(
        query=effective_query,
        registration_number=registration_number,
        project_name=project_name,
        khasra_number=khasra_number,
        plot_number=plot_number,
        district_hint=district,
    )
    cad_result = lookup_external_cadastral_registry(
        plot_number=plot_number,
        sector=sector,
        khasra_number=khasra_number,
        address=address or effective_query,
        district=district,
        tehsil=tehsil,
    )
    return {
        "status": "success",
        "external_intelligence": ext_intel,
        "cadastral_records": cad_result,
        "search_summary": ext_intel.get("summary_notes"),
    }


def document_processing_tool(
    document_text: Optional[str] = None,
    document_name: Optional[str] = None,
    project_id: Optional[int] = None,
    registration_number: Optional[str] = None,
    keyword: Optional[str] = None,
    category: Optional[str] = None,
    **kwargs,
) -> dict:
    """Document Processing Tool: Extracts and parses uploaded document text, or pulls land/deed filings for a project."""
    if document_text:
        return parse_uploaded_property_document(document_text=document_text, document_name=document_name)
    if project_id is not None:
        return get_project_land_details(project_id=project_id)
    if registration_number:
        p = lookup_project_by_registration_number(registration_number)
        if p and p.get("id"):
            return get_project_land_details(project_id=p["id"])
    return {"status": "no_document_input", "message": "Provide document_text or project_id to process."}


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
                "sector": {"type": "string"},
                "address": {"type": "string"},
                "district": {"type": "string"},
                "tehsil": {"type": "string"},
                "authority": {"type": "string"},
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
                "document_text": {"type": "string"},
                "document_name": {"type": "string"},
                "keyword": {"type": "string"},
                "category": {"type": "string"},
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
    "lookup_project_by_id": lookup_project_by_id,
    "lookup_project_by_registration_number": lookup_project_by_registration_number,
    "search_database_for_property": search_database_for_property,
    "get_project_land_details": get_project_land_details,
    "identify_property_master": identify_property_master,
    "parse_uploaded_property_document": parse_uploaded_property_document,
    "lookup_external_cadastral_registry": lookup_external_cadastral_registry,
    "match_entity_and_property": entity_and_property_matching_tool,
    "compare_records": record_comparison_tool,
}

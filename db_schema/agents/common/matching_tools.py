"""
Entity & Property Matching Tool + Record Comparison Tool.

Adapted from the app/tools/entity_property_matching and
app/tools/record_comparison modules you uploaded - logic is
unchanged, just simplified to return plain dicts (matching the style
every other tool in this codebase uses) instead of dataclasses, so
they drop straight into the Anthropic/Ollama tool-calling loop
without extra glue code.

Shared under common/ (not property_identification/) because every
subagent that ever compares two structured records - Property
Identification, Ownership & Title, Registration & Encumbrance - needs
the same two operations:

  match_entity_and_property(record_a, record_b)
      "Do these two records describe the same person/property?"
      Field-level exact-match comparison over a fixed set of entity
      fields (seller, buyer, owner) and property fields (plot_number,
      khasra_number, village, tehsil, district). Returns per-group
      confidence + which fields matched/mismatched.

  compare_records(record_a, record_b)
      "Where do these two records agree, conflict, or have gaps?"
      Generic field-by-field diff over EVERY key present in either
      record (not just a fixed set) - use this to reconcile, e.g., a
      RERA structured field against a document-extracted field for
      the same project.

Both are pure functions - no I/O, no DB, deterministic - so they're
cheap and safe for the model to call as often as it wants.
"""

from typing import Any

ENTITY_FIELDS = ["seller", "buyer", "owner"]
PROPERTY_FIELDS = ["plot_number", "khasra_number", "village", "tehsil", "district"]


def _compare_fields(
    record_a: dict[str, Any],
    record_b: dict[str, Any],
    fields: list[str],
) -> tuple[list[str], list[str], int]:
    matched, mismatched, compared = [], [], 0

    for field in fields:
        value_a = record_a.get(field)
        value_b = record_b.get(field)

        if value_a is None or value_b is None:
            continue  # can't compare a field neither/one record has

        compared += 1
        (matched if value_a == value_b else mismatched).append(field)

    return matched, mismatched, compared


def _confidence(matched: int, compared: int) -> float:
    return 0.0 if compared == 0 else round(matched / compared, 3)


def match_entity_and_property(record_a: dict, record_b: dict) -> dict:
    """
    Determine whether two records refer to the same entity (person)
    and/or the same property, via exact field-value comparison.

    V1: exact matching only - "RAM KUMAR" vs "Ram Kumar" will NOT
    match. If you need fuzzy name matching, normalize case/whitespace
    before calling this, or use search_projects' rapidfuzz scoring
    for free-text comparisons instead.
    """

    matched_entity, mismatched_entity, entity_compared = _compare_fields(
        record_a, record_b, ENTITY_FIELDS
    )
    matched_property, mismatched_property, property_compared = _compare_fields(
        record_a, record_b, PROPERTY_FIELDS
    )

    entity_match = entity_compared > 0 and not mismatched_entity
    property_match = property_compared > 0 and not mismatched_property

    reasons = []
    if entity_match:
        reasons.append("Available entity fields match.")
    elif mismatched_entity:
        reasons.append("One or more entity fields do not match.")
    else:
        reasons.append("No comparable entity fields were available.")

    if property_match:
        reasons.append("Available property fields match.")
    elif mismatched_property:
        reasons.append("One or more property fields do not match.")
    else:
        reasons.append("No comparable property fields were available.")

    return {
        "entity_match": entity_match,
        "property_match": property_match,
        "entity_confidence": _confidence(len(matched_entity), entity_compared),
        "property_confidence": _confidence(len(matched_property), property_compared),
        "matched_entity_fields": matched_entity,
        "matched_property_fields": matched_property,
        "mismatched_entity_fields": mismatched_entity,
        "mismatched_property_fields": mismatched_property,
        "reasons": reasons,
    }


def compare_records(record_a: dict, record_b: dict) -> dict:
    """
    Generic field-by-field diff of two records, over every key
    present in either one (not a fixed field list).

    matches               fields present + equal in both
    conflicts             fields present in both but with different values
    missing_in_record_a   fields present in record_b only
    missing_in_record_b   fields present in record_a only
    """

    matches, conflicts = [], []
    missing_in_a, missing_in_b = [], []

    all_fields = set(record_a.keys()) | set(record_b.keys())

    for field in sorted(all_fields):
        value_a = record_a.get(field)
        value_b = record_b.get(field)
        has_a, has_b = value_a is not None, value_b is not None

        if has_a and has_b:
            if value_a == value_b:
                matches.append(field)
            else:
                conflicts.append(
                    {"field": field, "record_a_value": value_a, "record_b_value": value_b}
                )
        elif has_a:
            missing_in_b.append(field)
        elif has_b:
            missing_in_a.append(field)

    return {
        "matches": matches,
        "conflicts": conflicts,
        "missing_in_record_a": missing_in_a,
        "missing_in_record_b": missing_in_b,
    }


TOOL_SCHEMAS = [
    {
        "name": "match_entity_and_property",
        "description": (
            "Compare two records field-by-field to check whether they refer "
            "to the same PERSON (seller/buyer/owner fields) and/or the same "
            "PROPERTY (plot_number/khasra_number/village/tehsil/district "
            "fields). Exact match only, no fuzzy tolerance. Use this to "
            "confirm identity between, e.g., a DB record and a "
            "document-extracted record."
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
        "name": "compare_records",
        "description": (
            "Diff two records field-by-field over EVERY key present in "
            "either one - not a fixed field list. Returns which fields "
            "match, which conflict (present in both but different values), "
            "and which are missing from each side. Use this to reconcile "
            "RERA structured fields against document-extracted fields."
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
    "match_entity_and_property": match_entity_and_property,
    "compare_records": compare_records,
}

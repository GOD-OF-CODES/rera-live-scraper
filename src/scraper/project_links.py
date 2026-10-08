"""Resolve internal UP-RERA IDs from the public search response, never a reg. number.

The GridView keeps its internal ID and S/N flag in non-rendered Label controls.
Their values are serialized in the response's ASP.NET ViewState. New registration
numbers are random six-digit identifiers and are NOT those internal IDs.
"""

import re
from urllib.parse import urljoin, urlparse, parse_qs

from bs4 import BeautifulSoup
from viewstate import ViewState

BASE_URL = "https://up-rera.in/"
DETAILS_URL = BASE_URL + "Frm_View_Project_Details.aspx?id={}"
REGISTRATION = re.compile(r"UPRERAPRJ\d+(?:/\d{2}/\d{4})?", re.I)


def normalize_registration(value):
    return re.sub(r"\s+", "", str(value or "")).upper()


def normalize_details_url(value, base_url=BASE_URL):
    """Accept only actual detail links, including relative and window.open URLs."""
    if not value:
        return None
    match = re.search(r"(?:https?://(?:www\.)?up-rera\.in/|/)?"
                      r"Frm_View_Project_Details\.aspx\?[^\s'\"<>)]*", value, re.I)
    if not match:
        return None
    candidate = urljoin(base_url, match.group(0))
    parsed = urlparse(candidate)
    ids = parse_qs(parsed.query).get("id", [])
    if parsed.hostname not in {"up-rera.in", "www.up-rera.in"} or len(ids) != 1 or not ids[0].isdigit():
        return None
    return DETAILS_URL.format(ids[0])


def _strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _strings(item)


def project_ids_from_viewstate(encoded):
    """Read GridView row controls; fail closed on unknown/corrupt layouts.

Each row has indexed children: 0=internal labels, 1=serial, 2=registration,
3=name, ... . We inspect this structure rather than pairing nearby digit strings
or assuming registration order. The decoder parses data; it executes no .NET code.
"""
    if not encoded:
        return {}
    decoded = ViewState(encoded).decode()
    found = {}

    def walk(node):
        if not isinstance(node, (list, tuple)):
            return
        if (len(node) == 2 and isinstance(node[1], list)
                and len(node[1]) >= 8 and len(node[1]) % 2 == 0):
            children = node[1]
            keys = children[::2]
            if keys[:4] == [0, 1, 2, 3] and all(isinstance(k, int) for k in keys):
                cells = dict(zip(keys, children[1::2]))
                ids = [s for s in _strings(cells[0]) if re.fullmatch(r"[1-9]\d*", s)]
                regs = [normalize_registration(s) for s in _strings(cells[2]) if REGISTRATION.fullmatch(s)]
                serials = [s for s in _strings(cells[1]) if s.isdigit()]
                if len(ids) == len(regs) == len(serials) == 1:
                    reg, project_id = regs[0], ids[0]
                    if reg in found and found[reg] != project_id:
                        raise ValueError(f"Conflicting internal project IDs for {reg}")
                    found[reg] = project_id
                    return
        for child in node:
            walk(child)

    walk(decoded)
    return found


def project_ids_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    parts = [soup.find(id="__VIEWSTATE")]
    count = soup.find(id="__VIEWSTATEFIELDCOUNT")
    if count:
        parts.extend(soup.find(id=f"__VIEWSTATE{i}") for i in range(1, int(count.get("value", "1"))))
    if not parts[0]:
        return {}
    if any(p is None for p in parts):
        raise ValueError("Search response contains an incomplete split ViewState")
    return project_ids_from_viewstate("".join(p.get("value", "") for p in parts))

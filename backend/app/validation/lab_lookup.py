"""POC lab accreditation and CPSC citation lookup from JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


def _load() -> dict[str, Any]:
    path = get_settings().lab_accreditation_file
    if not path.exists():
        return {"labs": [], "cpsc_citation_index": []}
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_lab_name(name: str | None) -> str:
    if not name:
        return ""
    return " ".join(name.lower().split())


def find_lab(name: str | None, accession: str | None) -> dict[str, Any] | None:
    data = _load()
    n = normalize_lab_name(name)
    acc = (accession or "").strip().upper()
    for lab in data.get("labs", []):
        if acc and lab.get("cpsc_accreditation_id", "").upper() == acc:
            return lab
        if n and lab.get("normalized_name", "") in n or n in lab.get("normalized_name", ""):
            return lab
    return None


def lab_supports_citation(lab: dict[str, Any] | None, citation: str) -> bool:
    if not lab:
        return False
    supported = lab.get("citations_supported") or []
    c = citation.strip().upper()
    return any(s.upper() in c or c in s.upper() for s in supported)


def cpsc_has_requirement(citation: str) -> bool:
    data = _load()
    idx = data.get("cpsc_citation_index") or []
    c = citation.strip().upper()
    return any(i.upper() in c or c in i.upper() for i in idx)

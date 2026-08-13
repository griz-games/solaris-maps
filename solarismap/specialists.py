"""The specialist table, and the rules about which ones a custom galaxy may use.

Data comes from specialists.json, which is generated out of the editor's own
store by sync_specialists.py - never hand-edit it. Solaris only accepts a
specialist flagged `active.custom`, so `is_custom_star_specialist` is the check
a builder wants before putting a specialistId on a star.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

TABLE_PATH = Path(__file__).resolve().parent / "specialists.json"


@functools.lru_cache(maxsize=1)
def _table() -> dict[str, list[dict]]:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


def star_specialists(custom_only: bool = True) -> list[dict]:
    return [s for s in _table()["star"] if s["active"]["custom"] or not custom_only]


def carrier_specialists(custom_only: bool = True) -> list[dict]:
    return [s for s in _table()["carrier"] if s["active"]["custom"] or not custom_only]


def star_specialist(specialist_id: int) -> dict | None:
    return next((s for s in _table()["star"] if s["id"] == specialist_id), None)


def carrier_specialist(specialist_id: int) -> dict | None:
    return next((s for s in _table()["carrier"] if s["id"] == specialist_id), None)


def is_custom_star_specialist(specialist_id: int) -> bool:
    """True if Solaris will accept this star specialist in a custom galaxy."""
    spec = star_specialist(specialist_id)
    return spec is not None and spec["active"]["custom"]


def is_custom_carrier_specialist(specialist_id: int) -> bool:
    spec = carrier_specialist(specialist_id)
    return spec is not None and spec["active"]["custom"]


def by_name(name: str, kind: str = "star") -> dict:
    """Look a specialist up by its display name, e.g. 'Telescope Array'.

    Raises rather than returning None: a builder that names a specialist that
    does not exist has a bug, and finding out at map-build time beats finding
    out when Solaris rejects the map.
    """
    pool = _table()["star" if kind == "star" else "carrier"]
    match = next((s for s in pool if s["name"].lower() == name.lower()), None)
    if match is None:
        raise KeyError(f"no {kind} specialist named {name!r}; "
                       f"have {sorted(s['name'] for s in pool)}")
    return match


def scanning_bonus(specialist_id: int | None) -> int:
    """Scanning modifier a star specialist contributes, 0 if it has none."""
    if specialist_id is None:
        return 0
    spec = star_specialist(specialist_id)
    if spec is None:
        return 0
    return spec.get("modifiers", {}).get("local", {}).get("scanning", 0) or 0

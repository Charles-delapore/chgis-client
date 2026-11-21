"""Data model and record parsing for the CHGIS Temporal Gazetteer (TGAZ).

Two shapes of data come back from the TGAZ API:

* Faceted search results: flat dicts with keys like ``"sys_id"``,
  ``"xy coordinates"`` (``"lon, lat"``) and ``"years"`` (``"1367 ~ 1911"``).
* Canonical records (``/placename/json/{id}``): nested dicts with
  ``"spellings"``, ``"temporal"``, ``"spatial"`` and
  ``"historical_context"``.

Both parse into :class:`Place`. Nothing here touches the network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# No real TGAZ place lies within 10 degrees of longitude 0; many POLYGON
# records repeat a place that also has a POINT row but carry longitude
# 0.00000 (a few carry 1-5), and some carry 0, 0.
_BAD_LON_ABS = 10.0

_YEAR_RANGE_RE = re.compile(r"(-?\d+)\s*~\s*(-?\d+)")


def _to_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def has_bad_coords(longitude: Optional[float], latitude: Optional[float]) -> bool:
    """True when a coordinate pair cannot be a real TGAZ place."""
    if longitude is None or latitude is None:
        return True
    return abs(longitude) < _BAD_LON_ABS or latitude == 0


@dataclass
class Place:
    """One historical place, as returned by the TGAZ API or the local cache."""

    sys_id: str
    name: str = ""
    transcription: str = ""
    feature_type: str = ""
    begin_year: Optional[int] = None
    end_year: Optional[int] = None
    longitude: Optional[float] = None
    latitude: Optional[float] = None
    object_type: str = ""
    parent_sys_id: Optional[str] = None
    parent_name: str = ""
    data_source: str = ""
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def bad_coords(self) -> bool:
        return has_bad_coords(self.longitude, self.latitude)

    @property
    def years(self) -> str:
        if self.begin_year is None and self.end_year is None:
            return ""
        return f"{self.begin_year} ~ {self.end_year}"

    def in_year(self, year: Optional[int]) -> bool:
        """True when this place existed in ``year`` (None means no filter)."""
        if year is None:
            return True
        if self.begin_year is not None and year < self.begin_year:
            return False
        if self.end_year is not None and year > self.end_year:
            return False
        return True

    def point(self) -> Optional[tuple[float, float]]:
        """(longitude, latitude), or None when the coordinates are unusable."""
        if self.bad_coords:
            return None
        return (self.longitude, self.latitude)  # type: ignore[return-value]

    # -- parsing ---------------------------------------------------------

    @classmethod
    def from_search_result(cls, result: dict) -> "Place":
        """Parse one flat faceted-search result dict."""
        lon = lat = None
        xy = result.get("xy coordinates")
        if isinstance(xy, str) and "," in xy:
            lon_s, lat_s = (v.strip() for v in xy.split(",", 1))
            lon, lat = _to_float(lon_s), _to_float(lat_s)
        begin = end = None
        years = result.get("years", "")
        if isinstance(years, str):
            m = _YEAR_RANGE_RE.search(years)
            if m:
                begin, end = _to_int(m.group(1)), _to_int(m.group(2))
        return cls(
            sys_id=str(result.get("sys_id", "")),
            name=str(result.get("name", "")),
            transcription=str(result.get("transcription", "")),
            feature_type=str(result.get("feature type", "")),
            begin_year=begin,
            end_year=end,
            longitude=lon,
            latitude=lat,
            object_type=str(result.get("object type", "")),
            parent_sys_id=str(result.get("parent sys_id") or "") or None,
            parent_name=str(result.get("parent name", "")),
            data_source=str(result.get("data source", "")),
            raw=dict(result),
        )

    @classmethod
    def from_record(cls, record: dict) -> "Place":
        """Parse one canonical record dict (``/placename/json/{id}``)."""
        name = name_of(record)
        transcription = transcription_of(record)
        begin, end = temporal_span(record)
        spatial = record.get("spatial", {}) if isinstance(record.get("spatial"), dict) else {}
        ftype = feature_type_of(record)
        parent = None
        parts = record.get("historical_context", {}).get("part of", []) if isinstance(
            record.get("historical_context"), dict
        ) else []
        if isinstance(parts, dict):
            parts = [parts]
        if parts:
            parent = parts[0]
        return cls(
            sys_id=str(record.get("sys_id", "")),
            name=name,
            transcription=transcription,
            feature_type=ftype,
            begin_year=_to_int(begin) if begin != "" else None,
            end_year=_to_int(end) if end != "" else None,
            longitude=_to_float(spatial.get("longitude")),
            latitude=_to_float(spatial.get("latitude")),
            object_type=str(spatial.get("object_type", "")),
            parent_sys_id=parent.get("parent id") if parent else None,
            parent_name=parent.get("name", "") if parent else "",
            data_source=str(record.get("data_source", "")),
            raw=dict(record),
        )


# -- field extractors for canonical records ------------------------------


def name_of(record: dict) -> str:
    """Primary Chinese name: traditional spelling first, then simplified."""
    for spelling in record.get("spellings", []) or []:
        if spelling.get("script") == "traditional Chinese":
            return spelling.get("written form", "")
    for spelling in record.get("spellings", []) or []:
        if spelling.get("script") == "simplified Chinese":
            return spelling.get("written form", "")
    return str(record.get("name", ""))


def transcription_of(record: dict) -> str:
    """Romanized transcription, preferring Pinyin."""
    for spelling in record.get("spellings", []) or []:
        if spelling.get("transcribed in") == "Pinyin":
            return spelling.get("written form", "")
    for spelling in record.get("spellings", []) or []:
        if "transcribed in" in spelling:
            return spelling.get("written form", "")
    return str(record.get("transcription", ""))


def temporal_span(record: dict) -> tuple[str, str]:
    """(begin, end) year strings from a canonical record ("" when absent)."""
    temporal = record.get("temporal", {})
    if not isinstance(temporal, dict):
        return ("", "")
    return (str(temporal.get("begin", "")), str(temporal.get("end", "")))


def modern_location(record: dict) -> str:
    """Modern equivalent location text (``;``-joined when several)."""
    spatial = record.get("spatial", {})
    if not isinstance(spatial, dict):
        return ""
    present = spatial.get("present_location", "")
    if isinstance(present, dict):
        present = [present]
    if isinstance(present, list):
        return "; ".join(p.get("text", "") for p in present if p.get("text"))
    return str(present)


def feature_type_of(record: dict) -> str:
    """Feature type in English when available, else transcription or name."""
    ftype = record.get("feature_type", {})
    if isinstance(ftype, dict):
        return ftype.get("English") or ftype.get("transcription") or ftype.get("name", "")
    return str(ftype)


def subordinates_of(record: dict) -> list[dict]:
    """Direct subordinate units of a canonical record (may be empty)."""
    context = record.get("historical_context", {})
    if not isinstance(context, dict):
        return []
    parts = context.get("subordinate units", [])
    if isinstance(parts, dict):
        return [parts]
    return list(parts)


def parents_of(record: dict) -> list[dict]:
    """``part of`` entries of a canonical record (may be empty).

    Note the key spelling differs from subordinate units: ``"begin year"``
    / ``"end year"`` (with spaces) here, ``"begin_year"`` / ``"end_year"``
    (with underscores) there.
    """
    context = record.get("historical_context", {})
    if not isinstance(context, dict):
        return []
    parts = context.get("part of", [])
    if isinstance(parts, dict):
        return [parts]
    return list(parts)


def squash(text: str) -> str:
    """Lower-case and drop spaces and apostrophes: ``"Chang'an"`` -> ``"changan"``.

    TGAZ writes one name as ``"Su Zhou"`` and ``"Suzhou Fu"``, or as
    ``"Changan Xian"`` and ``"Chang'an Xian"``; comparing squashed forms
    makes romanized matching robust to that.
    """
    for ch in (" ", "'", "’"):
        text = text.replace(ch, "")
    return text.lower()

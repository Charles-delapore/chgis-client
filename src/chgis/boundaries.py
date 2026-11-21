"""Read user-downloaded CHGIS administrative-boundary shapefiles.

This library ships **no CHGIS data**. Download the shapefiles yourself
from the CHGIS site (``CHGIS_DATA_URL`` below; some downloads need a free
registration) and point :func:`boundaries` at the directory that holds
them. Files are matched by the year in their filename (e.g.
``CHGIS_1820_prefectures.shp``) and, when a level is given, by a level
token in the filename (``xian``/``fu``/``zhou``/``sheng``/``dao``/``lu``/
``jun`` and their English equivalents).

Row filtering: when the shapefile carries a year range
(``BEG_YR``/``END_YR``, ``begin_year``/``end_year``, ``BEG``/``END`` or a
single ``YEAR`` column), rows are filtered to the requested year. When no
year column is present the whole file is returned as-is (the year is then
whatever the filename says) and that is recorded in ``gdf.attrs``.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd

from .errors import DataNotAvailableError

# Starting point for CHGIS data downloads (some files need registration).
CHGIS_DATA_URL = "https://chgis.fairbank.fas.harvard.edu/"

# (begin column, end column) pairs, tried in order.
YEAR_RANGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("BEG_YR", "END_YR"),
    ("begin_year", "end_year"),
    ("BEG", "END"),
    ("begin", "end"),
)
SINGLE_YEAR_COLUMNS = ("YEAR", "year")

LEVEL_TOKENS: dict[str, str] = {
    "xian": "xian",
    "county": "xian",
    "counties": "xian",
    "fu": "fu",
    "prefecture": "fu",
    "prefectures": "fu",
    "zhou": "zhou",
    "sheng": "sheng",
    "province": "sheng",
    "provinces": "sheng",
    "dao": "dao",
    "circuit": "dao",
    "lu": "lu",
    "route": "lu",
    "jun": "jun",
    "commandery": "jun",
}

_YEAR_RE = re.compile(r"(\d{3,4})")


def _year_from_filename(path: Path) -> Optional[int]:
    """First plausible year (100-1911) found in the filename, else None."""
    for token in _YEAR_RE.findall(path.name):
        year = int(token)
        if 100 <= year <= 1911:
            return year
    return None


def _level_from_filename(path: Path) -> Optional[str]:
    stem = path.stem.lower()
    for token, level in LEVEL_TOKENS.items():
        if token in stem:
            return level
    return None


def _resolve_data_dir(data_dir: Optional[Path | str]) -> Path:
    import os

    if data_dir is not None:
        return Path(data_dir).expanduser()
    env = os.environ.get("CHGIS_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / "chgis-data"


def _year_columns(columns) -> Optional[tuple[str, str] | str]:
    lower = {c.lower(): c for c in columns}
    for begin, end in YEAR_RANGE_COLUMNS:
        if begin.lower() in lower and end.lower() in lower:
            return (lower[begin.lower()], lower[end.lower()])
    for single in SINGLE_YEAR_COLUMNS:
        if single.lower() in lower:
            return lower[single.lower()]
    return None


def list_available(data_dir: Optional[Path | str] = None) -> list[dict]:
    """Scan a directory for CHGIS shapefiles.

    Returns ``[{"file", "year", "level", "rows"}, ...]`` sorted by year
    then level. ``rows`` is the feature count of each file.
    """
    directory = _resolve_data_dir(data_dir)
    if not directory.is_dir():
        raise DataNotAvailableError(
            f"no CHGIS data directory at {directory}. Download CHGIS shapefiles "
            f"from {CHGIS_DATA_URL} (some files need registration) and pass the "
            "directory as data_dir=, or set $CHGIS_DATA_DIR."
        )
    found = []
    for shp in sorted(directory.rglob("*.shp")):
        try:
            gdf = gpd.read_file(shp)
        except Exception as exc:  # unreadable file: report, don't crash the scan
            warnings.warn(f"could not read {shp}: {exc}")
            continue
        found.append(
            {
                "file": str(shp),
                "year": _year_from_filename(shp),
                "level": _level_from_filename(shp),
                "rows": len(gdf),
            }
        )
    found.sort(key=lambda d: (d["year"] is None, d["year"] or 0, d["level"] or ""))
    return found


def boundaries(
    year: int,
    level: Optional[str] = None,
    data_dir: Optional[Path | str] = None,
) -> "gpd.GeoDataFrame":
    """Administrative divisions for ``year`` as a GeoDataFrame.

    Args:
        year: historical year (e.g. 1820).
        level: optional level filter (``"xian"``, ``"fu"``, ``"zhou"``,
            ``"sheng"``, ``"dao"``, ``"lu"``, ``"jun"``; ``"county"`` /
            ``"prefecture"`` / ``"province"`` are accepted as aliases).
        data_dir: directory holding downloaded CHGIS shapefiles
            (default: ``$CHGIS_DATA_DIR`` or ``~/chgis-data``).

    Matching files are concatenated. ``gdf.attrs`` records the year, the
    level, the source files and whether rows were year-filtered.
    """
    if not (1 <= year <= 1911):
        raise ValueError(f"year must be between 1 and 1911, got {year}")
    if level is not None:
        level = LEVEL_TOKENS.get(level.lower(), level.lower())
    directory = _resolve_data_dir(data_dir)
    available = list_available(directory)
    matches = [
        a
        for a in available
        if a["year"] == year and (level is None or a["level"] == level)
    ]
    if not matches:
        have = ", ".join(
            f"{a['year'] or '?'}/{a['level'] or '?'}"
            for a in available
        ) or "none"
        raise DataNotAvailableError(
            f"no CHGIS shapefile for year={year}"
            + (f" level={level}" if level else "")
            + f" in {directory}. Available: {have}. Download the files from "
            f"{CHGIS_DATA_URL}."
        )
    frames = []
    filtered = False
    for match in matches:
        gdf = gpd.read_file(match["file"])
        cols = _year_columns(gdf.columns)
        if isinstance(cols, tuple):
            begin, end = cols
            beg = pd.to_numeric(gdf[begin], errors="coerce")
            fin = pd.to_numeric(gdf[end], errors="coerce")
            gdf = gdf[(beg <= year) & (fin >= year)]
            filtered = True
        elif isinstance(cols, str):
            gdf = gdf[pd.to_numeric(gdf[cols], errors="coerce") == year]
            filtered = True
        frames.append(gdf)
    if len(frames) == 1:
        out = frames[0]
    else:
        out = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    out.attrs.update(
        {
            "chgis_year": year,
            "chgis_level": level,
            "chgis_source_files": [m["file"] for m in matches],
            "chgis_year_filtered": filtered,
        }
    )
    return out

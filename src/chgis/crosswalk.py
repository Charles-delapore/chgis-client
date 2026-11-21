"""Crosswalk between historical placenames and modern GB/T 2260 codes.

Ships only a small table of the 34 provincial-level GB/T 2260 codes
(public standard data, not CHGIS data). County-level mapping needs a
user-supplied CSV — see :class:`Crosswalk`.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Optional

import geopandas as gpd

# (gb_code, name_zh, pinyin) — provincial-level GB/T 2260, public standard.
PROVINCES: tuple[tuple[str, str, str], ...] = (
    ("11", "北京", "Beijing"),
    ("12", "天津", "Tianjin"),
    ("13", "河北", "Hebei"),
    ("14", "山西", "Shanxi"),
    ("15", "内蒙古", "Inner Mongolia"),
    ("21", "辽宁", "Liaoning"),
    ("22", "吉林", "Jilin"),
    ("23", "黑龙江", "Heilongjiang"),
    ("31", "上海", "Shanghai"),
    ("32", "江苏", "Jiangsu"),
    ("33", "浙江", "Zhejiang"),
    ("34", "安徽", "Anhui"),
    ("35", "福建", "Fujian"),
    ("36", "江西", "Jiangxi"),
    ("37", "山东", "Shandong"),
    ("41", "河南", "Henan"),
    ("42", "湖北", "Hubei"),
    ("43", "湖南", "Hunan"),
    ("44", "广东", "Guangdong"),
    ("45", "广西", "Guangxi"),
    ("46", "海南", "Hainan"),
    ("50", "重庆", "Chongqing"),
    ("51", "四川", "Sichuan"),
    ("52", "贵州", "Guizhou"),
    ("53", "云南", "Yunnan"),
    ("54", "西藏", "Tibet"),
    ("61", "陕西", "Shaanxi"),
    ("62", "甘肃", "Gansu"),
    ("63", "青海", "Qinghai"),
    ("64", "宁夏", "Ningxia"),
    ("65", "新疆", "Xinjiang"),
    ("71", "台湾", "Taiwan"),
    ("81", "香港", "Hong Kong"),
    ("82", "澳门", "Macao"),
)


def provinces() -> list[dict]:
    """All 34 provincial-level entries as ``{"gb_code", "name_zh", "pinyin"}``."""
    return [
        {"gb_code": code, "name_zh": name, "pinyin": pinyin}
        for code, name, pinyin in PROVINCES
    ]


def province_by_code(code: str | int) -> Optional[dict]:
    """Look up a province by GB/T 2260 code (``"33"`` or ``33``)."""
    code = str(code).zfill(2)
    for entry in provinces():
        if entry["gb_code"] == code:
            return entry
    return None


def province_by_name(name: str) -> Optional[dict]:
    """Look up a province by Chinese name or pinyin (case-insensitive)."""
    needle = name.strip().lower().replace(" ", "")
    for entry in provinces():
        if needle in (entry["name_zh"], entry["pinyin"].lower().replace(" ", "")):
            return entry
    return None


class Crosswalk:
    """Historical-name -> modern GB/T 2260 code mapping from a user CSV.

    CSV columns: ``name`` (historical name, as written in your data),
    ``gb_code`` (6-digit county code, or 2-digit province code), and
    optionally ``year_start`` / ``year_end`` (the years the mapping holds
    for). Rows without a year range apply to every year.

    Example CSV::

        name,gb_code,year_start,year_end
        苏州府,320500,1367,1911
        吴县,320501,1367,1911
    """

    def __init__(self, rows: list[dict]):
        self.rows = rows

    @classmethod
    def from_csv(cls, path: Path | str) -> "Crosswalk":
        rows = []
        with open(path, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                name = (row.get("name") or "").strip()
                code = (row.get("gb_code") or "").strip()
                if not name or not code:
                    continue
                start = (row.get("year_start") or "").strip()
                end = (row.get("year_end") or "").strip()
                rows.append(
                    {
                        "name": name,
                        "gb_code": code,
                        "year_start": int(start) if start.lstrip("-").isdigit() else None,
                        "year_end": int(end) if end.lstrip("-").isdigit() else None,
                    }
                )
        return cls(rows)

    def lookup(self, name: str, year: Optional[int] = None) -> Optional[dict]:
        """Best mapping for ``name`` (exact match), preferring a row whose
        year range contains ``year`` when one is given. When ``year`` is
        given and no dated row covers it, an undated row still applies;
        otherwise there is no mapping for that year."""
        name = name.strip()
        dated = [
            r for r in self.rows
            if r["name"] == name
            and (r["year_start"] is not None or r["year_end"] is not None)
        ]
        undated = [
            r for r in self.rows
            if r["name"] == name
            and r["year_start"] is None and r["year_end"] is None
        ]
        if year is not None:
            for row in dated:
                start_ok = row["year_start"] is None or year >= row["year_start"]
                end_ok = row["year_end"] is None or year <= row["year_end"]
                if start_ok and end_ok:
                    return row
            if undated:
                return undated[0]
            return None
        return (dated or undated or [None])[0]

    def attach(
        self,
        gdf: "gpd.GeoDataFrame",
        name_col: str,
        year_col: Optional[str] = None,
        out_col: str = "gb_code",
    ) -> "gpd.GeoDataFrame":
        """Return a copy of ``gdf`` with a GB code column joined on the
        historical name (and year, when ``year_col`` is given)."""
        out = gdf.copy()
        codes = []
        for _, row in out.iterrows():
            year = None
            if year_col is not None and year_col in out.columns:
                try:
                    year = int(row[year_col])
                except (TypeError, ValueError):
                    year = None
            hit = self.lookup(str(row[name_col]), year)
            codes.append(hit["gb_code"] if hit else None)
        import pandas as pd

        out[out_col] = pd.Series(codes, index=out.index, dtype=object)
        return out

"""Tests for the GB/T 2260 crosswalk."""

import geopandas as gpd
import pytest
from shapely.geometry import box

from chgis.crosswalk import Crosswalk, province_by_code, province_by_name, provinces


def test_provinces_table():
    all_provinces = provinces()
    assert len(all_provinces) == 34
    assert {p["gb_code"] for p in all_provinces} == {
        "11", "12", "13", "14", "15", "21", "22", "23", "31", "32", "33",
        "34", "35", "36", "37", "41", "42", "43", "44", "45", "46", "50",
        "51", "52", "53", "54", "61", "62", "63", "64", "65", "71", "81", "82",
    }


def test_province_by_code():
    assert province_by_code("33")["name_zh"] == "浙江"
    assert province_by_code(11)["pinyin"] == "Beijing"
    assert province_by_code("99") is None


def test_province_by_name():
    assert province_by_name("浙江")["gb_code"] == "33"
    assert province_by_name("Zhejiang")["gb_code"] == "33"
    assert province_by_name("zhejiang")["gb_code"] == "33"
    assert province_by_name("不存在") is None


def _csv(tmp_path, text):
    path = tmp_path / "crosswalk.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_crosswalk_lookup(tmp_path):
    path = _csv(
        tmp_path,
        "name,gb_code,year_start,year_end\n"
        "苏州府,320500,1367,1911\n"
        "吴县,320501,1367,1911\n"
        "苏州,320500,,\n",
    )
    cw = Crosswalk.from_csv(path)
    assert cw.lookup("苏州府", 1820)["gb_code"] == "320500"
    assert cw.lookup("苏州府", 2000) is None  # outside the dated range...
    # ...but the undated 苏州 row does not match 苏州府 (exact match only).
    assert cw.lookup("苏州", 2000)["gb_code"] == "320500"
    assert cw.lookup("不存在") is None


def test_crosswalk_attach(tmp_path):
    path = _csv(tmp_path, "name,gb_code,year_start,year_end\n吴县,320501,1367,1911\n")
    cw = Crosswalk.from_csv(path)
    gdf = gpd.GeoDataFrame(
        [{"NAME": "吴县", "YEAR": 1820}, {"NAME": "长洲县", "YEAR": 1820}],
        geometry=[box(0, 0, 1, 1), box(1, 0, 2, 1)],
        crs="EPSG:4326",
    )
    out = cw.attach(gdf, "NAME", year_col="YEAR")
    assert list(out["gb_code"]) == ["320501", None]
    assert "gb_code" not in gdf.columns  # input untouched

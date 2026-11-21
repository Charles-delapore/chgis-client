"""Tests for LocalCache — all offline, against a tiny built tgaz.db."""

import sqlite3

import pytest

from chgis.cache import LocalCache
from chgis.errors import CacheError


def test_search_name_prefix(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        places = cache.search_name("苏州")
        assert {p.sys_id for p in places} == {"hvd_32432", "hvd_90246"}


def test_search_name_romanized_squashed(tgaz_db_path):
    # "Su Zhou" vs "Suzhou": spaces are ignored in the transcription match.
    # Prefix matching also catches 酥州司 ("Suzhousi").
    with LocalCache(tgaz_db_path) as cache:
        places = cache.search_name("su zhou")
        assert {p.sys_id for p in places} == {"hvd_32432", "hvd_90246", "hvd_21531"}


def test_search_name_traditional_spelling(tgaz_db_path):
    # Traditional 蘇州府 finds the place via the spelling table.
    with LocalCache(tgaz_db_path) as cache:
        places = cache.search_name("蘇州府")
        assert {p.sys_id for p in places} == {"hvd_32432", "hvd_90246"}


def test_search_name_year_filter(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        places = cache.search_name("苏州", year=1500)
        assert {p.sys_id for p in places} == {"hvd_32432"}
        # The POLYGON row starts 1724, so it drops out for 1500.


def test_search_name_good_coords(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        places = cache.search_name("苏州", good_coords=True)
        assert {p.sys_id for p in places} == {"hvd_32432"}


def test_search_name_feature_type(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        # "county" maps to TGAZ terms (xian...) — no county named 苏州 here.
        assert cache.search_name("苏州", feature_type="county") == []
        # "prefecture" maps to fu: both 苏州府 rows match.
        places = cache.search_name("苏州", feature_type="prefecture")
        assert {p.sys_id for p in places} == {"hvd_32432", "hvd_90246"}


def test_search_name_parent_at_year(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        places = cache.search_name("苏州", year=1500)
        assert places[0].parent_sys_id == "hvd_30040"
        assert places[0].parent_name == "江南行省"


def test_search_by_year(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        places = cache.search_by_year(800)
        assert {p.sys_id for p in places} == {"hvd_32180"}
        places = cache.search_by_year(1820)
        assert {p.sys_id for p in places} == {"hvd_32432", "hvd_90246", "hvd_21531"}


def test_search_bbox(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        places = cache.search_bbox(119, 29, 121, 32)
        assert {p.sys_id for p in places} == {"hvd_32432", "hvd_32180", "hvd_30040"}
        # The lon-0 POLYGON row is outside any China bbox.
        assert "hvd_90246" not in {p.sys_id for p in places}


def test_get_by_id(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        place = cache.get_by_id("hvd_32180")
        assert place is not None
        assert place.name == "婺州"
        assert place.raw["spellings"] == ["婺州"]
        assert cache.get_by_id("hvd_00000") is None


def test_stats(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        stats = cache.stats()
        assert stats["places"] == 5
        assert stats["spellings"] == 5
        assert stats["min_begin_year"] == 758
        assert stats["max_end_year"] == 1911
        assert stats["bad_coords_rows"] == 1  # only the hvd_90246 POLYGON row


def test_parents_at_year(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        parents = cache.parents_at_year(["hvd_32432", "hvd_32180"], 1500)
        assert parents["hvd_32432"]["parent_sys_id"] == "hvd_30040"
        # 婺州's part_of row ends 1275, so no parent in 1500.
        assert "hvd_32180" not in parents


def test_missing_db(tmp_path):
    with pytest.raises(CacheError, match="no database"):
        LocalCache(tmp_path / "missing.db")


def test_wrong_schema(tmp_path):
    path = tmp_path / "wrong.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE foo (a TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(CacheError, match="missing tables"):
        LocalCache(path)


def test_lfs_pointer(tmp_path):
    path = tmp_path / "tgaz.db"
    path.write_bytes(b"version https://git-lfs.example/pointer")
    with pytest.raises(CacheError, match="LFS pointer"):
        LocalCache(path)


def test_context_manager_closes(tgaz_db_path):
    cache = LocalCache(tgaz_db_path)
    with cache:
        assert cache.search_name("婺州")
    with pytest.raises(Exception):
        cache.search_name("婺州")

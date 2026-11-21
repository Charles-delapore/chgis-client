"""Tests for resolve() — API path (mocked) and cache path (tiny db)."""

import json

import pytest

from chgis.cache import LocalCache
from chgis.client import TGAZClient
from chgis.resolve import resolve

from conftest import load_fixture
from test_client import FakeResponse, FakeSession


def _api_client():
    search_payload = load_fixture("search_suzhou_1820.json")
    suzhou_record = {
        "sys_id": "hvd_32432",
        "spellings": [
            {"script": "traditional Chinese", "written form": "蘇州府"},
            {"transcribed in": "Pinyin", "written form": "Suzhou Fu"},
        ],
        "feature_type": {"English": "superior prefecture", "name": "府"},
        "temporal": {"begin": "1367", "end": "1911"},
        "spatial": {"object_type": "POINT", "latitude": "31.31271",
                    "longitude": "120.61862"},
        "historical_context": {
            "part of": [
                {"begin year": "1367", "end year": "1911",
                 "parent id": "hvd_30040", "name": "江南行省",
                 "transcribed": "Jiangnan Xings"}
            ]
        },
    }
    jiangnan_record = {
        "sys_id": "hvd_30040",
        "spellings": [{"script": "traditional Chinese", "written form": "江南行省"}],
        "feature_type": {"English": "province", "name": "行省"},
        "temporal": {"begin": "1276", "end": "1367"},
        "spatial": {"object_type": "POINT", "latitude": "31.0", "longitude": "120.0"},
        "historical_context": {"part of": []},
    }
    session = FakeSession(
        [
            ("placename?n=", FakeResponse(200, search_payload)),
            ("placename/json/hvd_32432", FakeResponse(200, suzhou_record)),
            ("placename/json/hvd_30040", FakeResponse(200, jiangnan_record)),
        ]
    )
    return TGAZClient(min_interval=0, session=session)


def test_resolve_api_picks_point_record():
    client = _api_client()
    result = resolve("苏州府", year=1820, client=client)
    assert result is not None
    assert result.place.sys_id == "hvd_32432"  # POINT, not the lon-0 POLYGONs
    assert result.source == "api"
    assert result.candidates == 2  # drop_bad_coords left 2 of the 4
    assert result.chain_names() == ["苏州府", "江南行省"]
    assert result.place.point() == (120.61862, 31.31271)


def test_resolve_api_no_match():
    session = FakeSession(
        [("placename?n=", FakeResponse(200, {"placenames": []}))]
    )
    client = TGAZClient(min_interval=0, session=session)
    assert resolve("不存在的地名", year=1820, client=client) is None


def test_resolve_id_direct_lookup():
    record = load_fixture("record_hvd_32180.json")
    session = FakeSession(
        [
            ("placename/json/hvd_32180", FakeResponse(200, record)),
            # The chain walk fetches the parent next; it has no parent itself.
            (
                "placename/json/hvd_30083",
                FakeResponse(
                    200,
                    {"sys_id": "hvd_30083", "historical_context": {"part of": []}},
                ),
            ),
        ]
    )
    client = TGAZClient(min_interval=0, session=session)
    result = resolve("32180", client=client)
    assert result is not None
    assert result.place.name == "婺州"
    assert result.candidates == 1
    # 婺州's first "part of" entry is 浙江东道节度使.
    assert result.chain[0]["sys_id"] == "hvd_30083"


def test_resolve_cache_path(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        result = resolve("苏州府", year=1500, cache=cache)
        assert result is not None
        assert result.place.sys_id == "hvd_32432"
        assert result.source == "cache"
        assert result.chain_names() == ["苏州府", "江南行省"]


def test_resolve_cache_no_match(tgaz_db_path):
    with LocalCache(tgaz_db_path) as cache:
        assert resolve("不存在", cache=cache) is None


def test_resolve_prefers_exact_match():
    # Both 苏州府 (exact) and 酥州司 (prefix-adjacent) are candidates;
    # the exact name must win even though 酥州司 also matches the year.
    client = _api_client()
    result = resolve("苏州府", year=1820, client=client)
    assert result.place.name == "苏州府"
    assert result.place.sys_id == "hvd_32432"

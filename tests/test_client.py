"""Tests for TGAZClient — all offline, the API is mocked with fixtures."""

import json

import pytest
import requests

from chgis.client import BASE_URL, TGAZClient
from chgis.errors import ApiError, NotFoundError
from chgis.models import Place

from conftest import load_fixture


class FakeResponse:
    def __init__(self, status=200, payload=None, text=None, headers=None):
        self.status_code = status
        self._payload = payload
        self.headers = headers or {}
        if text is not None:
            self.text = text
        elif payload is not None:
            self.text = json.dumps(payload)
        else:
            self.text = ""

    def json(self):
        return self._payload


class FakeSession:
    """A requests-like session serving canned responses keyed by URL."""

    def __init__(self, routes):
        # routes: list of (url_substring, FakeResponse) in priority order
        self.routes = list(routes)
        self.calls = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        full = url
        if params:
            from urllib.parse import urlencode

            full = f"{url}?{urlencode(params)}"
        for needle, resp in self.routes:
            if needle in full:
                if isinstance(resp, list):
                    return resp.pop(0)
                return resp
        raise AssertionError(f"no fake route for {full}")


def _search_client():
    session = FakeSession(
        [("placename?n=", FakeResponse(200, load_fixture("search_suzhou_1820.json")))]
    )
    return TGAZClient(min_interval=0, session=session)


def test_search_returns_places():
    client = _search_client()
    places = client.search("suzhou", year=1820)
    assert len(places) == 4
    first = places[0]
    assert isinstance(first, Place)
    assert first.sys_id == "hvd_32432"
    assert first.name == "苏州府"
    assert first.transcription == "Suzhou Fu"
    assert (first.begin_year, first.end_year) == (1367, 1911)
    assert first.longitude == pytest.approx(120.61862)
    assert first.latitude == pytest.approx(31.31271)
    assert first.object_type == "POINT"
    assert first.parent_sys_id == "hvd_30040"


def test_search_drop_bad_coords():
    client = _search_client()
    places = client.search("suzhou", year=1820, drop_bad_coords=True)
    assert {p.sys_id for p in places} == {"hvd_32432", "hvd_21531"}
    assert all(not p.bad_coords for p in places)


def test_search_limit():
    client = _search_client()
    places = client.search("suzhou", year=1820, limit=1)
    assert len(places) == 1


def test_search_bad_coords_detection():
    client = _search_client()
    places = client.search("suzhou", year=1820)
    by_id = {p.sys_id: p for p in places}
    assert by_id["hvd_90246"].bad_coords is True  # lon 0 POLYGON duplicate
    assert by_id["hvd_2027"].bad_coords is True  # 0, 0
    assert by_id["hvd_32432"].bad_coords is False
    assert by_id["hvd_32432"].point() == (120.61862, 31.31271)
    assert by_id["hvd_2027"].point() is None


def test_year_validation():
    client = _search_client()
    with pytest.raises(ValueError):
        client.search("suzhou", year=2000)
    with pytest.raises(ValueError):
        client.search("suzhou", year=-300)


def test_get_by_id_parses_record():
    record = load_fixture("record_hvd_32180.json")
    session = FakeSession([("placename/json/hvd_32180", FakeResponse(200, record))])
    client = TGAZClient(min_interval=0, session=session)
    place = client.get_place("hvd_32180")
    assert place.name == "婺州"
    assert place.transcription == "Wu Zhou"
    assert (place.begin_year, place.end_year) == (758, 1275)
    assert place.longitude == pytest.approx(119.64992)
    assert place.latitude == pytest.approx(29.10471)
    assert place.feature_type == "prefecture"
    assert place.parent_sys_id == "hvd_30083"
    assert place.parent_name == "浙江东道节度使"


def test_get_by_id_bare_number_gets_prefix():
    record = load_fixture("record_hvd_32180.json")
    session = FakeSession([("placename/json/hvd_32180", FakeResponse(200, record))])
    client = TGAZClient(min_interval=0, session=session)
    place = client.get_place("32180")
    assert place.sys_id == "hvd_32180"
    assert session.calls[0][0].endswith("/placename/json/hvd_32180")


def test_get_by_id_bad_fmt():
    client = TGAZClient(min_interval=0, session=FakeSession([]))
    with pytest.raises(ValueError):
        client.get_by_id("hvd_32180", fmt="yaml")


def test_get_by_id_404():
    session = FakeSession([("placename/json/hvd_99999", FakeResponse(404, text="<html>nope</html>"))])
    client = TGAZClient(min_interval=0, session=session)
    with pytest.raises(NotFoundError):
        client.get_by_id("hvd_99999")


def test_retry_on_429_then_success():
    payload = load_fixture("search_suzhou_1820.json")
    session = FakeSession(
        [
            (
                "placename?n=",
                [
                    FakeResponse(429, text="slow down", headers={"Retry-After": "0"}),
                    FakeResponse(200, payload),
                ],
            )
        ]
    )
    client = TGAZClient(min_interval=0, max_retries=3, session=session)
    places = client.search("suzhou", year=1820)
    assert len(places) == 4
    assert len(session.calls) == 2


def test_retry_exhausted_raises():
    session = FakeSession(
        [("placename?n=", [FakeResponse(503, text="down") for _ in range(5)])]
    )
    client = TGAZClient(min_interval=0, max_retries=2, session=session)
    with pytest.raises(ApiError) as excinfo:
        client.search("suzhou", year=1820)
    assert excinfo.value.status == 503
    assert len(session.calls) == 3  # 1 try + 2 retries


def test_record_helpers():
    record = load_fixture("record_hvd_32180.json")
    client = TGAZClient(min_interval=0, session=FakeSession([]))
    assert client.name_of(record) == "婺州"
    assert client.transcription_of(record) == "Wu Zhou"
    assert client.temporal_span(record) == ("758", "1275")
    assert client.modern_location(record) == "今浙江金华市"
    assert client.feature_type_of(record) == "prefecture"
    assert len(client.subordinates_of(record)) == 1
    summary = client.summarize(record)
    assert "婺州" in summary and "758" in summary and "金华" in summary


def _record_with_subordinates(children):
    return {
        "sys_id": "hvd_parent",
        "historical_context": {"subordinate units": children},
    }


def test_get_descendants_two_levels():
    province = _record_with_subordinates(
        [
            {"child id": "hvd_100", "name": "杭州府", "begin_year": "1400", "end_year": "1911"},
            {"child id": "hvd_101", "name": "宁波府", "begin_year": "1400", "end_year": "1911"},
        ]
    )
    hangzhou = _record_with_subordinates(
        [
            {"child id": "hvd_200", "name": "钱塘县", "begin_year": "1400", "end_year": "1911"},
            {"child id": "hvd_201", "name": "仁和县", "begin_year": "1400", "end_year": "1800"},
        ]
    )
    ningbo = _record_with_subordinates([])
    session = FakeSession(
        [
            ("placename/json/hvd_30015", FakeResponse(200, province)),
            ("placename/json/hvd_100", FakeResponse(200, hangzhou)),
            ("placename/json/hvd_101", FakeResponse(200, ningbo)),
        ]
    )
    client = TGAZClient(min_interval=0, session=session)
    found = client.get_descendants("hvd_30015", year=1850, levels=2)
    got = {(d["child id"], d["level"]) for d in found}
    # 仁和县 ended 1800, so it is excluded for year 1850.
    assert got == {("hvd_100", 1), ("hvd_101", 1), ("hvd_200", 2)}
    assert all(d["parent id"] for d in found)


def test_get_ancestors_walks_part_of():
    child = {
        "sys_id": "hvd_32180",
        "historical_context": {
            "part of": [
                {"begin year": "758", "end year": "769", "parent id": "hvd_30083",
                 "name": "浙江东道节度使", "transcribed": "Zhejiang Dongdao"},
                {"begin year": "770", "end year": "1275", "parent id": "hvd_30084",
                 "name": "两浙路", "transcribed": "Liangzhe Lu"},
            ]
        },
    }
    parent = {"sys_id": "hvd_30084", "historical_context": {"part of": []}}
    session = FakeSession(
        [
            ("placename/json/hvd_32180", FakeResponse(200, child)),
            ("placename/json/hvd_30084", FakeResponse(200, parent)),
        ]
    )
    client = TGAZClient(min_interval=0, session=session)
    chain = client.get_ancestors("hvd_32180", year=800)
    assert [c["sys_id"] for c in chain] == ["hvd_30084"]
    assert chain[0]["name"] == "两浙路"


def test_user_agent_set():
    session = requests.Session()
    TGAZClient(min_interval=0, session=session)
    assert "chgis-client" in session.headers["User-Agent"]

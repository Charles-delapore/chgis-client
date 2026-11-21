"""Client for the CHGIS Temporal Gazetteer (TGAZ) API.

Live API: ``https://chgis.hudci.org/tgaz/placename`` (the old
``maps.cga.harvard.edu`` domain is dead). Valid years are -222 to 1911
(222 BCE to 1911 CE).

Search quirks worth knowing (all documented upstream):

* ``n`` uses prefix matching: ``"beijing"`` also matches 北京路, 北京行省...
* Some romanizations differ from modern pinyin (Ningbo -> ``"Ningpo"``).
* Some records split syllables with a space: 苏州 before 1367 is
  ``"Su Zhou"``, so ``"suzhou"`` with ``year=1100`` finds nothing.
  Search Chinese characters when you can (蘇州 or 苏州 both work).
* The ``ipar`` (parent) search parameter is unreliable. For hierarchy
  queries use :meth:`TGAZClient.get_descendants` / :meth:`get_ancestors`,
  which read a record's subordinate / ``part of`` lists instead.
* Many places have a second POLYGON record (often an ``hvd_90xxx`` id)
  whose longitude is 0 (or 1-5). Pass ``drop_bad_coords=True`` to drop
  those before plotting.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import requests

from .errors import ApiError, NotFoundError
from .models import (
    Place,
    feature_type_of,
    modern_location,
    name_of,
    parents_of,
    squash,
    subordinates_of,
    temporal_span,
    transcription_of,
)

BASE_URL = "https://chgis.hudci.org/tgaz/placename"
USER_AGENT = "chgis-client/0.1.0 (+https://github.com/Charles-delapore)"
MIN_YEAR = -222
MAX_YEAR = 1911
FORMATS = ("json", "xml", "rdf")


def _check_year(year: Optional[int]) -> None:
    if year is not None and not (MIN_YEAR <= year <= MAX_YEAR):
        raise ValueError(f"year must be between {MIN_YEAR} and {MAX_YEAR}, got {year}")


class TGAZClient:
    """Thin client for the TGAZ API (``requests``-based).

    Args:
        min_interval: minimum seconds between requests (default 1.0;
            be polite to a shared academic service).
        max_retries: retries on 429 / 5xx (default 3). Other 4xx errors
            fail at once. ``Retry-After`` is honored when present.
        timeout: per-request timeout in seconds.
        session: optional :class:`requests.Session` (mainly for tests).
    """

    def __init__(
        self,
        min_interval: float = 1.0,
        max_retries: int = 3,
        timeout: int = 30,
        session: Optional[requests.Session] = None,
    ):
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._timeout = timeout
        self._session = session or requests.Session()
        current_ua = self._session.headers.get("User-Agent", "")
        if not current_ua or current_ua.startswith("python-requests/"):
            self._session.headers["User-Agent"] = USER_AGENT
        self._last_request = 0.0

    # -- transport -------------------------------------------------------

    def _rate_limit(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.time()

    @staticmethod
    def _retry_delay(response: requests.Response, attempt: int) -> float:
        retry_after = response.headers.get("Retry-After")
        if retry_after and retry_after.strip().isdigit():
            return min(60.0, float(retry_after.strip()))
        return min(8.0, 0.5 * (2 ** attempt))

    def _get(self, url: str, params: Optional[dict] = None) -> Any:
        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            self._rate_limit()
            try:
                resp = self._session.get(url, params=params, timeout=self._timeout)
            except requests.RequestException as exc:
                last_error = ApiError(f"request failed: {exc}")
                if attempt < self._max_retries:
                    time.sleep(min(8.0, 0.5 * (2 ** attempt)))
                    continue
                raise last_error
            if resp.status_code == 404:
                raise NotFoundError(f"not found: {url}", status=404)
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                raise ApiError(
                    f"API error {resp.status_code} for {url}", status=resp.status_code
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                last_error = ApiError(
                    f"API error {resp.status_code} for {url}", status=resp.status_code
                )
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay(resp, attempt))
                    continue
                raise last_error
            ctype = resp.headers.get("Content-Type", "")
            if "json" in ctype or resp.text.lstrip().startswith(("{", "[")):
                return resp.json()
            return resp.text
        raise last_error or ApiError("request failed")

    # -- search ----------------------------------------------------------

    def search(
        self,
        name: str,
        year: Optional[int] = None,
        feature_type: Optional[str] = None,
        parent: Optional[str] = None,
        drop_bad_coords: bool = False,
        limit: Optional[int] = None,
    ) -> list[Place]:
        """Faceted search for placenames.

        Args:
            name: place name (Chinese characters or romanization).
            year: historical year (-222 to 1911; negative for BCE).
            feature_type: administrative type (``xian``, ``fu``, ``zhou``,
                ``sheng``, ``dao``, ``lu``, ``jun``...).
            parent: parent administrative unit name (``ipar``; unreliable
                upstream — prefer :meth:`get_descendants` for hierarchy).
            drop_bad_coords: drop results whose coordinates are broken
                (longitude < 10 or latitude 0).
            limit: keep at most this many results (after filtering).
        """
        _check_year(year)
        params: dict[str, str] = {"n": name, "fmt": "json"}
        if year is not None:
            params["yr"] = str(year)
        if feature_type:
            params["ftyp"] = feature_type
        if parent:
            params["ipar"] = parent
        data = self._get(BASE_URL, params)
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            raw = data.get("placenames", data.get("results", [data]))
        else:
            raw = []
        places = [Place.from_search_result(r) for r in raw if isinstance(r, dict)]
        if drop_bad_coords:
            places = [p for p in places if not p.bad_coords]
        if limit is not None:
            places = places[:limit]
        return places

    # -- canonical records -------------------------------------------------

    def get_by_id(self, tgaz_id: str, fmt: str = "json") -> Any:
        """Retrieve one record by TGAZ ID.

        The format is part of the URL path, not a query parameter:
        ``/placename/json/{id}``. ``"json"`` returns a dict; ``"xml"``
        and ``"rdf"`` return raw text. A bare number gets the ``hvd_``
        prefix automatically (``32180`` -> ``hvd_32180``).
        """
        if fmt not in FORMATS:
            raise ValueError(f"fmt must be one of {FORMATS}, got {fmt!r}")
        tgaz_id = str(tgaz_id).strip()
        if tgaz_id.isdigit():
            tgaz_id = f"hvd_{tgaz_id}"
        url = f"{BASE_URL}/{fmt}/{tgaz_id}"
        return self._get(url)

    def get_place(self, tgaz_id: str) -> Place:
        """Retrieve one record by ID and parse it into a :class:`Place`."""
        record = self.get_by_id(tgaz_id, fmt="json")
        if not isinstance(record, dict):
            raise ApiError(f"unexpected response for {tgaz_id}: {record!r}")
        return Place.from_record(record)

    # -- hierarchy ---------------------------------------------------------

    def get_descendants(
        self, tgaz_id: str, year: Optional[int] = None, levels: int = 2
    ) -> list[dict]:
        """Drill down the hierarchy, ``levels`` steps below a unit.

        A province's record lists only the next level (prefectures 府/州/厅);
        counties sit one level lower, so "all counties in Zhejiang" needs
        ``levels=2`` (one request for the province plus one per prefecture).
        Each returned unit carries ``"level"`` (1 = direct child) and
        ``"parent id"``. Units are filtered to ``year`` and each child id
        is returned once.
        """
        _check_year(year)
        found: list[dict] = []
        seen: set[str] = set()
        frontier = [str(tgaz_id)]
        for level in range(1, levels + 1):
            next_frontier: list[str] = []
            for parent_id in frontier:
                record = self.get_by_id(parent_id)
                for unit in subordinates_of(record):
                    child = unit.get("child id")
                    if not child or child in seen:
                        continue
                    if year is not None:
                        try:
                            if not (int(unit["begin_year"]) <= year <= int(unit["end_year"])):
                                continue
                        except (KeyError, TypeError, ValueError):
                            continue
                    seen.add(child)
                    found.append({**unit, "level": level, "parent id": parent_id})
                    next_frontier.append(child)
            frontier = next_frontier
        return found

    def get_ancestors(
        self, tgaz_id: str, year: Optional[int] = None, max_steps: int = 6
    ) -> list[dict]:
        """Walk up the hierarchy via each record's ``part of`` list.

        Returns ``[{"sys_id", "name", "feature_type", "begin_year",
        "end_year"}, ...]`` from the immediate parent upwards. Entries are
        filtered to ``year`` when given (the first entry covering that year
        wins at each step). Stops after ``max_steps`` or when a record has
        no parent.
        """
        _check_year(year)
        chain: list[dict] = []
        current = str(tgaz_id)
        for _ in range(max_steps):
            record = self.get_by_id(current)
            parents = parents_of(record)
            if not parents:
                break
            chosen = None
            for entry in parents:
                if year is None:
                    chosen = entry
                    break
                try:
                    if int(entry["begin year"]) <= year <= int(entry["end year"]):
                        chosen = entry
                        break
                except (KeyError, TypeError, ValueError):
                    continue
            if chosen is None:
                break
            parent_id = chosen.get("parent id")
            if not parent_id:
                break
            chain.append(
                {
                    "sys_id": parent_id,
                    "name": chosen.get("name", ""),
                    "feature_type": chosen.get("transcribed", ""),
                    "begin_year": chosen.get("begin year"),
                    "end_year": chosen.get("end year"),
                }
            )
            current = parent_id
        return chain

    # -- record helpers (also exposed at module level) ---------------------

    @staticmethod
    def name_of(record: dict) -> str:
        return name_of(record)

    @staticmethod
    def transcription_of(record: dict) -> str:
        return transcription_of(record)

    @staticmethod
    def temporal_span(record: dict) -> tuple[str, str]:
        return temporal_span(record)

    @staticmethod
    def modern_location(record: dict) -> str:
        return modern_location(record)

    @staticmethod
    def feature_type_of(record: dict) -> str:
        return feature_type_of(record)

    @staticmethod
    def subordinates_of(record: dict) -> list[dict]:
        return subordinates_of(record)

    def summarize(self, record: dict) -> str:
        """One short human-readable summary of a canonical record."""
        lines = [f"# {name_of(record)} ({transcription_of(record)})"]
        ftype = feature_type_of(record)
        if ftype:
            lines.append(f"\n**Type:** {ftype}")
        begin, end = temporal_span(record)
        if begin or end:
            lines.append(f"**Period:** {begin} – {end}")
        modern = modern_location(record)
        if modern:
            lines.append(f"**Modern location:** {modern}")
        return "\n".join(lines)


def squash_name(name: str) -> str:
    """Lower-case a romanized name with spaces/apostrophes removed, for
    robust matching (``"Su Zhou"`` vs ``"Suzhou"``)."""
    return squash(name)

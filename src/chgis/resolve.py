"""Gazetteer disambiguation: ``resolve(name, year)``.

Picks the best TGAZ record for a historical placename and returns it with
its affiliation chain (parent, grandparent, ...) walked from the record's
``part of`` list (API) or the ``part_of`` table (local cache).

Ranking (best first): exact name match, then POINT records before POLYGON
records, then usable coordinates, then a record that existed in ``year``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .cache import LocalCache
from .client import TGAZClient
from .models import Place, squash

_ID_RE = re.compile(r"^(hvd_)?\d+$")


@dataclass
class ResolvedPlace:
    """The best record for a name, with its affiliation chain."""

    place: Place
    chain: list[dict] = field(default_factory=list)
    candidates: int = 0
    source: str = "api"

    @property
    def sys_id(self) -> str:
        return self.place.sys_id

    @property
    def longitude(self) -> Optional[float]:
        return self.place.longitude

    @property
    def latitude(self) -> Optional[float]:
        return self.place.latitude

    def chain_names(self) -> list[str]:
        """Affiliation chain as names, from the place itself upwards."""
        return [self.place.name] + [c.get("name", "") for c in self.chain]


def _rank_key(name: str, year: Optional[int]):
    squashed = squash(name)

    def key(place: Place) -> tuple:
        exact = 0 if (
            place.name == name
            or squash(place.name) == squashed
            or squash(place.transcription) == squashed
        ) else 1
        point = 0 if place.object_type == "POINT" else 1
        bad = 0 if not place.bad_coords else 1
        in_year = 0 if place.in_year(year) else 1
        begin = place.begin_year if place.begin_year is not None else 0
        return (exact, point, bad, in_year, begin)

    return key


def _api_chain(client: TGAZClient, sys_id: str, year: Optional[int]) -> list[dict]:
    return client.get_ancestors(sys_id, year=year)


def _cache_chain(cache: LocalCache, place: Place, year: Optional[int]) -> list[dict]:
    chain: list[dict] = []
    current = place.sys_id
    probe_year = year if year is not None else place.begin_year
    if probe_year is None:
        probe_year = 1820
    for _ in range(6):
        parents = cache.parents_at_year([current], probe_year)
        parent = parents.get(current)
        if not parent:
            break
        chain.append(
            {
                "sys_id": parent.get("parent_sys_id", ""),
                "name": parent.get("parent_vn", ""),
                "feature_type": parent.get("parent_tr", ""),
                "begin_year": None,
                "end_year": None,
            }
        )
        current = parent["parent_sys_id"]
    return chain


def resolve(
    name: str,
    year: Optional[int] = None,
    client: Optional[TGAZClient] = None,
    cache: Optional[LocalCache] = None,
    drop_bad_coords: bool = True,
    limit: int = 50,
) -> Optional[ResolvedPlace]:
    """Resolve a historical placename to its best TGAZ record.

    Args:
        name: place name (Chinese characters or romanization), or a TGAZ
            id (``"hvd_32180"`` or bare ``"32180"`` — looked up directly).
        year: historical year; used to filter and rank candidates.
        client: a :class:`TGAZClient` (default: a new one; needs network).
            When ``cache`` is given and ``client`` is not, the local
            database is used instead and no network is touched.
        cache: a :class:`LocalCache` (local ``tgaz.db``).
        drop_bad_coords: drop candidates with broken coordinates before
            ranking (longitude < 10 or latitude 0).
        limit: candidates considered from the search.

    Returns a :class:`ResolvedPlace` (``place`` + ``chain`` + how many
    candidates were considered), or None when nothing matches.
    """
    if _ID_RE.match(name.strip()):
        tgaz_id = name.strip()
        if tgaz_id.isdigit():
            tgaz_id = f"hvd_{tgaz_id}"
        if client is not None:
            place = client.get_place(tgaz_id)
            return ResolvedPlace(
                place=place,
                chain=_api_chain(client, tgaz_id, year),
                candidates=1,
                source="api",
            )
        if cache is not None:
            place = cache.get_by_id(tgaz_id)
            if place is None:
                return None
            return ResolvedPlace(
                place=place,
                chain=_cache_chain(cache, place, year),
                candidates=1,
                source="cache",
            )
        client = TGAZClient()
        place = client.get_place(tgaz_id)
        return ResolvedPlace(
            place=place,
            chain=_api_chain(client, tgaz_id, year),
            candidates=1,
            source="api",
        )

    if cache is not None and client is None:
        candidates = cache.search_name(name, year=year, limit=limit)
        source = "cache"
    else:
        client = client or TGAZClient()
        candidates = client.search(name, year=year, limit=limit)
        source = "api"

    if drop_bad_coords:
        good = [p for p in candidates if not p.bad_coords]
        if good:
            candidates = good
    if not candidates:
        return None

    best = sorted(candidates, key=_rank_key(name, year))[0]
    if source == "api":
        assert client is not None
        chain = _api_chain(client, best.sys_id, year)
    else:
        assert cache is not None
        chain = _cache_chain(cache, best, year)
    return ResolvedPlace(place=best, chain=chain, candidates=len(candidates), source=source)

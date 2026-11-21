"""Local SQLite cache for the TGAZ data.

The full gazetteer is available as one SQLite file (228 MB, 82,117 places)
published as the Hugging Face dataset ``kltng/tgaz-sqlite``. This module
downloads it once, verifies the SHA-256 checksums published in
``latest.json``, and queries it read-only.

License note: the upstream data has **no explicit licence file**. The
canonical API records carry ``"license": "CC BY-NC 4.0"``; the dataset page
says to credit CHGIS and check the CHGIS site for terms of use. This library
ships no data and never redistributes the database — it only downloads it
to the user's own machine on request.

Database layout (tables used here): ``mv_pn_srch`` (one row per place:
``sys_id, name, transcription, beg_yr, end_yr, obj_type, x_coord,
y_coord, ftype_vn, ftype_tr, parent_sys_id, parent_vn, parent_tr,
data_src``), ``spelling`` (``written_form, placename_id``),
``placename`` (``id, sys_id``), ``ftype`` (``name_en, name_tr``),
``part_of`` (``child_id, parent_id, begin_year, end_year``) and the
FTS5 table ``search_fts``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from .errors import CacheError
from .models import Place, has_bad_coords, squash

RELEASE_URL = "https://huggingface.co/datasets/kltng/tgaz-sqlite/resolve/main/latest.json"
USER_AGENT = "chgis-client/0.1.0 (+https://github.com/Charles-delapore)"

DEFAULT_DIR = Path.home() / ".local" / "share" / "chgis"
DEFAULT_DB = DEFAULT_DIR / "tgaz.db"

# Tables this module needs. Checked on open so a wrong file fails fast
# with a helpful message instead of a bare sqlite error.
REQUIRED_TABLES = ("mv_pn_srch", "spelling", "placename", "part_of", "ftype")

# English words that are not exact ftype.name_en values.
FEATURE_TYPE_ALIASES = {"kingdom": "country", "state": "country"}


def default_db_path() -> Path:
    """Database location: ``$TGAZ_DB`` wins, else ``~/.local/share/chgis/tgaz.db``."""
    env = os.environ.get("TGAZ_DB")
    if env:
        return Path(env).expanduser()
    return DEFAULT_DB


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _release_sidecar(db_path: Path) -> Path:
    return Path(db_path).with_name(Path(db_path).name + ".release.json")


def fetch_release() -> dict:
    """Read ``latest.json`` from Hugging Face (release name, URLs, checksums)."""
    resp = requests.get(RELEASE_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def download_db(dest: Optional[Path] = None, force: bool = False) -> Path:
    """Download the current TGAZ SQLite release, verifying checksums.

    Downloads the 62 MB zip, checks its SHA-256 against ``latest.json``,
    unzips the database and checks that SHA-256 too, then records the
    release in a ``<db>.release.json`` sidecar. Returns the database path.
    """
    dest = Path(dest).expanduser() if dest else DEFAULT_DB
    if dest.exists() and not force:
        return dest
    meta = fetch_release()
    dest.parent.mkdir(parents=True, exist_ok=True)
    archive = dest.with_name(meta["archive_filename"] + ".part")
    tmp_db = dest.with_name(dest.name + ".part")
    try:
        with requests.get(
            meta["download_url"], headers={"User-Agent": USER_AGENT}, timeout=600, stream=True
        ) as resp:
            resp.raise_for_status()
            with open(archive, "wb") as out:
                shutil.copyfileobj(resp.raw, out, 1 << 20)
        if _sha256(archive) != meta["archive_sha256"]:
            raise CacheError("downloaded archive failed its SHA-256 check; try again")
        with zipfile.ZipFile(archive) as z, z.open(meta["sqlite_filename"]) as src, open(
            tmp_db, "wb"
        ) as out:
            shutil.copyfileobj(src, out, 1 << 20)
        if _sha256(tmp_db) != meta["sha256"]:
            raise CacheError("unzipped database failed its SHA-256 check; try again")
        os.replace(tmp_db, dest)
    finally:
        for p in (archive, tmp_db):
            if p.exists():
                p.unlink()
    sidecar = {k: meta[k] for k in ("sqlite_filename", "sha256", "size_bytes", "release")}
    sidecar.update(
        format="sqlite3",
        stamped_at_utc=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    _release_sidecar(dest).write_text(json.dumps(sidecar, indent=2) + "\n", encoding="utf-8")
    return dest


def check_release(db_path: Optional[Path] = None) -> bool:
    """True when the local database matches the current release."""
    db_path = Path(db_path).expanduser() if db_path else DEFAULT_DB
    try:
        local = json.loads(_release_sidecar(db_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        local = {}
    meta = fetch_release()
    if not db_path.exists():
        return False
    return local.get("sha256") == meta["sha256"] or local.get("release") == meta["release"]


def _like_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


_BAD_COORDS_SQL = "(ABS(CAST(x_coord AS REAL)) < 10 OR CAST(y_coord AS REAL) = 0)"


def _row_to_place(row: sqlite3.Row) -> Place:
    d = dict(row)
    return Place(
        sys_id=d.get("sys_id", ""),
        name=d.get("name", "") or "",
        transcription=d.get("transcription", "") or "",
        feature_type=d.get("ftype_vn", "") or "",
        begin_year=d.get("beg_yr"),
        end_year=d.get("end_yr"),
        longitude=float(d["x_coord"]) if d.get("x_coord") not in (None, "") else None,
        latitude=float(d["y_coord"]) if d.get("y_coord") not in (None, "") else None,
        object_type=d.get("obj_type", "") or "",
        parent_sys_id=d.get("parent_sys_id") or None,
        parent_name=d.get("parent_vn", "") or "",
        data_source=d.get("data_src", "") or "",
        raw=d,
    )


class LocalCache:
    """Read-only queries against a local ``tgaz.db``.

    Args:
        db_path: explicit database path. When omitted, ``$TGAZ_DB`` wins,
            else ``~/.local/share/chgis/tgaz.db``. Use
            :func:`download_db` to fetch the database first.
    """

    def __init__(self, db_path: Optional[Path | str] = None):
        self.db_path = Path(db_path).expanduser() if db_path else default_db_path()
        if not self.db_path.exists():
            raise CacheError(
                f"no database at {self.db_path}. Download it with "
                f"chgis.cache.download_db() (62 MB zip, 228 MB unzipped) "
                f"or set $TGAZ_DB to an existing tgaz.db."
            )
        self._conn = self._connect()
        self._check_schema()

    def _connect(self) -> sqlite3.Connection:
        # Open read-only; a stray LFS pointer file fails the header check first.
        with open(self.db_path, "rb") as f:
            head = f.read(64)
        if head.startswith(b"version https://git-lfs"):
            raise CacheError(
                f"{self.db_path} is a Git LFS pointer file, not the database. "
                "Delete it and download the database instead."
            )
        if not head.startswith(b"SQLite format 3\x00"):
            raise CacheError(f"{self.db_path} is not a SQLite database.")
        conn = sqlite3.connect(self.db_path.resolve().as_uri() + "?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _check_schema(self) -> None:
        have = {
            r[0]
            for r in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = [t for t in REQUIRED_TABLES if t not in have]
        if missing:
            raise CacheError(
                f"{self.db_path} is missing tables: {', '.join(missing)}. "
                "It is probably not a TGAZ database."
            )

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "LocalCache":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- helpers -----------------------------------------------------------

    def _english_feature_terms(self, word: str) -> list[str]:
        """Map an English feature type ("county") to TGAZ terms (xian, gun...)."""
        word = FEATURE_TYPE_ALIASES.get(word.strip().lower(), word.strip().lower())
        rows = self._conn.execute(
            "SELECT DISTINCT name_tr FROM ftype WHERE name_en = ? COLLATE NOCASE "
            "AND name_tr <> ''",
            (word,),
        ).fetchall()
        return [r["name_tr"] for r in rows]

    def _feature_type_clause(self, feature_type: str, prefix: str = "") -> tuple[str, list]:
        terms = self._english_feature_terms(feature_type)
        if terms:
            marks = ", ".join("?" * len(terms))
            return f" AND LOWER({prefix}ftype_tr) IN ({marks})", [t.lower() for t in terms]
        ft = _like_escape(feature_type)
        return (
            f" AND ({prefix}ftype_tr LIKE ? ESCAPE '\\' OR {prefix}ftype_vn LIKE ? ESCAPE '\\')",
            [f"%{ft}%", f"%{ft}%"],
        )

    def parents_at_year(self, sys_ids: list[str], year: int) -> dict[str, dict]:
        """Map child sys_id -> its parent in ``year`` (from ``part_of``).

        ``mv_pn_srch.parent_*`` holds only the earliest parent; ``part_of``
        has every parent with its years.
        """
        found: dict[str, dict] = {}
        ids = list(dict.fromkeys(sys_ids))
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            marks = ", ".join("?" * len(chunk))
            for r in self._conn.execute(
                f"""SELECT c.sys_id AS child, p.sys_id AS parent_sys_id,
                           m.name AS parent_vn, m.transcription AS parent_tr
                    FROM part_of po
                    JOIN placename c ON po.child_id = c.id
                    JOIN placename p ON po.parent_id = p.id
                    LEFT JOIN mv_pn_srch m ON m.sys_id = p.sys_id
                    WHERE c.sys_id IN ({marks})
                      AND po.begin_year <= ? AND po.end_year >= ?
                    ORDER BY po.begin_year""",
                (*chunk, year, year),
            ):
                found.setdefault(r["child"], dict(r))
        return found

    def _with_parent_at_year(self, rows: list[sqlite3.Row], year: Optional[int]) -> list[dict]:
        if year is None or not rows:
            return [dict(r) for r in rows]
        parents = self.parents_at_year([r["sys_id"] for r in rows], year)
        out = []
        for r in rows:
            d = dict(r)
            p = parents.get(d["sys_id"])
            if p:
                d["parent_sys_id"] = p["parent_sys_id"]
                d["parent_vn"] = p["parent_vn"]
                d["parent_tr"] = p["parent_tr"]
            out.append(d)
        return out

    # -- queries -------------------------------------------------------------

    def search_name(
        self,
        name: str,
        year: Optional[int] = None,
        feature_type: Optional[str] = None,
        limit: int = 50,
        good_coords: bool = False,
    ) -> list[Place]:
        """Search by name (Chinese or romanized), with optional filters.

        Matches the start of the simplified name, of the romanized name
        (spaces/apostrophes ignored, so ``"Suzhou"`` also finds ``"Su Zhou"``),
        and of every spelling in the spelling table (so traditional
        characters find the place too).
        """
        prefix = _like_escape(name)
        squashed = _like_escape(squash(name))
        sql = f"""
            SELECT sys_id, name, transcription, beg_yr, end_yr, obj_type,
                   x_coord, y_coord, ftype_vn, ftype_tr,
                   parent_sys_id, parent_vn, parent_tr, data_src,
                   {_BAD_COORDS_SQL} AS bad_coords
            FROM mv_pn_srch
            WHERE (name LIKE ? ESCAPE '\\' OR transcription LIKE ? ESCAPE '\\'
                   OR (? <> '' AND LOWER(REPLACE(REPLACE(REPLACE(transcription, ' ', ''), char(39), ''), char(8217), '')) LIKE ? ESCAPE '\\')
                   OR sys_id IN (
                       SELECT p.sys_id FROM spelling s
                       JOIN placename p ON p.id = s.placename_id
                       WHERE s.written_form >= ? AND s.written_form < ?))
        """
        params: list = [
            f"{prefix}%", f"{prefix}%", squashed, f"{squashed}%",
            name, name + "\U0010ffff",
        ]
        if year is not None:
            sql += " AND beg_yr <= ? AND end_yr >= ?"
            params.extend([year, year])
        if feature_type:
            clause, more = self._feature_type_clause(feature_type)
            sql += clause
            params.extend(more)
        if good_coords:
            sql += f" AND NOT {_BAD_COORDS_SQL}"
        sql += " ORDER BY beg_yr LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_place(r) for r in self._with_parent_at_year(rows, year)]

    def search_by_year(
        self,
        year: int,
        feature_type: Optional[str] = None,
        limit: int = 50,
        good_coords: bool = False,
    ) -> list[Place]:
        """All places existing in a given year."""
        sql = f"SELECT *, {_BAD_COORDS_SQL} AS bad_coords FROM mv_pn_srch WHERE beg_yr <= ? AND end_yr >= ?"
        params: list = [year, year]
        if feature_type:
            clause, more = self._feature_type_clause(feature_type)
            sql += clause
            params.extend(more)
        if good_coords:
            sql += f" AND NOT {_BAD_COORDS_SQL}"
        sql += " ORDER BY name LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_place(r) for r in self._with_parent_at_year(rows, year)]

    def search_bbox(
        self,
        lon_min: float,
        lat_min: float,
        lon_max: float,
        lat_max: float,
        year: Optional[int] = None,
        limit: int = 100,
    ) -> list[Place]:
        """Places whose point falls inside a bounding box."""
        sql = f"""SELECT *, {_BAD_COORDS_SQL} AS bad_coords FROM mv_pn_srch
                  WHERE CAST(x_coord AS REAL) BETWEEN ? AND ?
                    AND CAST(y_coord AS REAL) BETWEEN ? AND ?"""
        params: list = [lon_min, lon_max, lat_min, lat_max]
        if year is not None:
            sql += " AND beg_yr <= ? AND end_yr >= ?"
            params.extend([year, year])
        sql += " ORDER BY name LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_place(r) for r in self._with_parent_at_year(rows, year)]

    def get_by_id(self, sys_id: str) -> Optional[Place]:
        """One place by ``sys_id`` (``hvd_32180``), or None when absent."""
        row = self._conn.execute(
            f"SELECT *, {_BAD_COORDS_SQL} AS bad_coords FROM mv_pn_srch WHERE sys_id = ?",
            (sys_id,),
        ).fetchone()
        if row is None:
            return None
        place = _row_to_place(row)
        spellings = self._conn.execute(
            """SELECT s.written_form FROM spelling s
               JOIN placename p ON p.id = s.placename_id
               WHERE p.sys_id = ?""",
            (sys_id,),
        ).fetchall()
        place.raw["spellings"] = [r[0] for r in spellings]
        return place

    def stats(self) -> dict:
        """Database statistics: counts, year span, bad-coordinate rows."""
        total = self._conn.execute("SELECT COUNT(*) FROM mv_pn_srch").fetchone()[0]
        spellings = self._conn.execute("SELECT COUNT(*) FROM spelling").fetchone()[0]
        span = self._conn.execute(
            "SELECT MIN(beg_yr), MAX(end_yr) FROM mv_pn_srch"
        ).fetchone()
        bad = self._conn.execute(
            f"SELECT COUNT(*) FROM mv_pn_srch WHERE {_BAD_COORDS_SQL}"
        ).fetchone()[0]
        return {
            "places": total,
            "spellings": spellings,
            "min_begin_year": span[0],
            "max_end_year": span[1],
            "bad_coords_rows": bad,
        }

    @staticmethod
    def has_bad_coords(longitude, latitude) -> bool:
        return has_bad_coords(longitude, latitude)

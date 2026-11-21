"""Shared fixtures: a tiny tgaz.db with the real schema (5 rows)."""

import json
import sqlite3
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def build_tiny_db(path: Path) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE mv_pn_srch (
            sys_id TEXT, name TEXT, transcription TEXT,
            beg_yr INTEGER, end_yr INTEGER, obj_type TEXT,
            x_coord TEXT, y_coord TEXT, ftype_vn TEXT, ftype_tr TEXT,
            parent_sys_id TEXT, parent_vn TEXT, parent_tr TEXT, data_src TEXT);
        CREATE TABLE spelling (written_form TEXT, placename_id INTEGER);
        CREATE TABLE placename (id INTEGER, sys_id TEXT);
        CREATE TABLE ftype (name_en TEXT, name_tr TEXT);
        CREATE TABLE part_of (child_id INTEGER, parent_id INTEGER,
                              begin_year INTEGER, end_year INTEGER);
        """
    )
    conn.executemany(
        "INSERT INTO placename VALUES (?, ?)",
        [(1, "hvd_32432"), (2, "hvd_90246"), (3, "hvd_32180"),
         (4, "hvd_30040"), (5, "hvd_21531")],
    )
    conn.executemany(
        "INSERT INTO mv_pn_srch VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("hvd_32432", "苏州府", "Suzhou Fu", 1367, 1911, "POINT",
             "120.61862", "31.31271", "府", "fu", "hvd_30040", "江南行省",
             "Jiangnan Xings", "CHGIS"),
            ("hvd_90246", "苏州府", "Suzhou Fu", 1724, 1911, "POLYGON",
             "0.00000", "31.312710", "府", "fu", "", "", "", "CHGIS"),
            ("hvd_32180", "婺州", "Wu Zhou", 758, 1275, "POINT",
             "119.64992", "29.10471", "州", "zhou", "hvd_30083",
             "浙江东道节度使", "", "CHGIS"),
            ("hvd_30040", "江南行省", "Jiangnan Xings", 1276, 1367, "POINT",
             "120.0", "31.0", "行省", "xingsheng", "", "", "", "CHGIS"),
            ("hvd_21531", "酥州司", "Suzhousi", 1820, 1820, "POINT",
             "102.24670", "28.79662", "村镇", "cun zhen", "hvd_9725",
             "宁远府", "Ningyuan Fu", "CHGIS"),
        ],
    )
    conn.executemany(
        "INSERT INTO spelling VALUES (?, ?)",
        [("蘇州府", 1), ("苏州府", 1), ("蘇州府", 2), ("苏州府", 2), ("婺州", 3)],
    )
    conn.executemany(
        "INSERT INTO ftype VALUES (?, ?)",
        [("county", "xian"), ("prefecture", "fu"),
         ("superior prefecture", "fu"), ("province", "sheng")],
    )
    conn.executemany(
        "INSERT INTO part_of VALUES (?, ?, ?, ?)",
        [(1, 4, 1367, 1911), (3, 4, 758, 1275)],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def tgaz_db_path(tmp_path):
    return build_tiny_db(tmp_path / "tgaz.db")

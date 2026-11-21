# chgis-client

Lightweight Python client for the **CHGIS Temporal Gazetteer (TGAZ)** —
historical China, 222 BCE–1911 CE: 82,117 placenames, 245,042 spellings,
83,400 affiliations (Harvard University & Fudan University).

There was no pip-installable Python library for TGAZ; this is one. It is
small on purpose: an API client, a local SQLite cache, a shapefile reader,
a GB/T 2260 crosswalk, and gazetteer disambiguation.

## Install

```bash
pip install .
```

Requires Python 3.10+, `requests`, `geopandas`, `pyproj`.

## Quick start — live API

```python
from chgis import TGAZClient, resolve

client = TGAZClient()

# Faceted search (prefix matching; Chinese characters work best)
places = client.search("苏州府", year=1820, drop_bad_coords=True)
for p in places:
    print(p.sys_id, p.name, p.transcription, p.years, p.point())
# hvd_32432 苏州府 Suzhou Fu 1367 ~ 1911 (120.61862, 31.31271)

# One record by id
place = client.get_place("hvd_32180")   # or "32180"
print(place.name, place.years)          # 婺州 758 ~ 1275

# Hierarchy: all counties of Zhejiang in 1850 (province -> prefectures -> counties)
children = client.get_descendants("hvd_30015", year=1850, levels=2)
parents = client.get_ancestors("hvd_32180", year=800)

# Disambiguation: best record + affiliation chain
best = resolve("苏州府", year=1820, client=client)
print(best.place.sys_id, best.chain_names())
# hvd_32432 ['苏州府', '江南行省']
```

Search quirks (documented upstream): `n` uses prefix matching; some
romanizations differ from modern pinyin (Ningbo → `"Ningpo"`); some records
split syllables with a space (`"Su Zhou"` before 1367). Many places have a
second POLYGON record (often an `hvd_90xxx` id) whose longitude is 0 —
pass `drop_bad_coords=True` before plotting.

## Local SQLite cache (no network after setup)

The full gazetteer is published as one SQLite file (228 MB) in the
Hugging Face dataset `kltng/tgaz-sqlite`. Download it once (checksums
verified against `latest.json`), then query it read-only:

```python
from chgis import LocalCache, download_db, resolve

download_db()                       # 62 MB zip -> 228 MB tgaz.db
with LocalCache() as cache:         # default: ~/.local/share/chgis/tgaz.db
    print(cache.stats())
    places = cache.search_name("苏州", year=1820, good_coords=True)
    places = cache.search_bbox(119, 29, 121, 32, year=1820)
    best = resolve("苏州府", year=1820, cache=cache)   # offline
```

`$TGAZ_DB` overrides the database path. `LocalCache` opens the file
read-only and refuses Git LFS pointer files and wrong-schema files with a
clear error.

## Historical boundaries (shapefiles you download)

```python
from chgis import boundaries, list_available

print(list_available("/path/to/chgis-data"))
# [{"file": ..., "year": 1820, "level": "fu", "rows": 312}, ...]

gdf = boundaries(1820, level="fu", data_dir="/path/to/chgis-data")
print(gdf.attrs)   # year, level, source files, whether rows were year-filtered
```

Download the shapefiles yourself from the CHGIS site
(<https://chgis.fairbank.fas.harvard.edu/>; some files need a free
registration) and point the library at the directory (`$CHGIS_DATA_DIR`
or `~/chgis-data` by default). Files are matched by the year in their
filename and, when a level is given, by a level token (`xian`/`fu`/`zhou`/
`sheng`/`dao`/`lu`/`jun`, or `county`/`prefecture`/`province` aliases).
Rows are filtered to the year when the file carries a year range
(`BEG_YR`/`END_YR`, `begin_year`/`end_year`, `BEG`/`END`, `YEAR`).

## GB/T 2260 crosswalk

```python
from chgis import Crosswalk, province_by_code, province_by_name

province_by_code("33")      # {"gb_code": "33", "name_zh": "浙江", "pinyin": "Zhejiang"}
province_by_name("Zhejiang")

cw = Crosswalk.from_csv("crosswalk.csv")   # name,gb_code[,year_start,year_end]
cw.lookup("苏州府", year=1820)             # {"name": "苏州府", "gb_code": "320500", ...}
gdf = cw.attach(gdf, "NAME", year_col="YEAR")
```

The library ships only the 34 provincial-level codes (public standard
data). County-level mapping comes from your own CSV.

## Data & licensing — read this

* **This library ships no CHGIS data.** It reads the live API, a local
  database you downloaded, or shapefiles you downloaded.
* TGAZ canonical records carry `"license": "CC BY-NC 4.0"` in the API
  response. The Hugging Face SQLite dump has **no explicit licence file**;
  its page says to credit CHGIS and check the CHGIS site for terms of use.
* **CBDB is out of scope.** No CBDB data is touched, and no CBDB
  placename linking is included, until the CBDB version and licence tier
  are confirmed.

## Tests

```bash
pip install -e ".[test]"
pytest -v
```

All tests run offline (mocked API responses, a tiny synthetic `tgaz.db`,
synthetic shapefiles).

## Status

0.1.0 — working core, not a complete product. Known gaps: no async
client; no bulk download of shapefiles; the crosswalk ships province
codes only; `boundaries()` guesses year columns from a fixed list.

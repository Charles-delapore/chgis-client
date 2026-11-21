"""Tests for boundaries() — synthetic shapefiles, no CHGIS data needed."""

import geopandas as gpd
import pytest
from shapely.geometry import box

from chgis.boundaries import boundaries, list_available
from chgis.errors import DataNotAvailableError


def _make_shapefile(directory, filename, rows):
    gdf = gpd.GeoDataFrame(
        rows,
        geometry=[box(i, 0, i + 1, 1) for i in range(len(rows))],
        crs="EPSG:4326",
    )
    path = directory / filename
    gdf.to_file(path)
    return path


@pytest.fixture
def data_dir(tmp_path):
    _make_shapefile(
        tmp_path,
        "CHGIS_1820_fu.shp",
        [
            {"NAME": "苏州府", "BEG_YR": 1367, "END_YR": 1911},
            {"NAME": "松江府", "BEG_YR": 1724, "END_YR": 1911},
            {"NAME": "太仓州", "BEG_YR": 1724, "END_YR": 1800},
        ],
    )
    _make_shapefile(
        tmp_path,
        "CHGIS_1750_fu.shp",
        [{"NAME": "苏州府", "BEG_YR": 1367, "END_YR": 1911}],
    )
    return tmp_path


def test_boundaries_year_filter(data_dir):
    gdf = boundaries(1820, data_dir=data_dir)
    assert set(gdf["NAME"]) == {"苏州府", "松江府"}  # 太仓州 ended 1800
    assert gdf.attrs["chgis_year"] == 1820
    assert gdf.attrs["chgis_year_filtered"] is True
    assert len(gdf.attrs["chgis_source_files"]) == 1


def test_boundaries_other_year(data_dir):
    gdf = boundaries(1750, data_dir=data_dir)
    assert set(gdf["NAME"]) == {"苏州府"}


def test_boundaries_level_filter(data_dir):
    gdf = boundaries(1820, level="fu", data_dir=data_dir)
    assert len(gdf) == 2
    gdf = boundaries(1820, level="prefecture", data_dir=data_dir)
    assert len(gdf) == 2


def test_boundaries_missing_year(data_dir):
    with pytest.raises(DataNotAvailableError, match="no CHGIS shapefile"):
        boundaries(1600, data_dir=data_dir)


def test_boundaries_missing_dir(tmp_path):
    with pytest.raises(DataNotAvailableError, match="no CHGIS data directory"):
        boundaries(1820, data_dir=tmp_path / "nope")


def test_list_available(data_dir):
    found = list_available(data_dir)
    assert [(f["year"], f["level"], f["rows"]) for f in found] == [
        (1750, "fu", 1),
        (1820, "fu", 3),
    ]


def test_boundaries_no_year_column(tmp_path):
    _make_shapefile(
        tmp_path,
        "CHGIS_1820_xian.shp",
        [{"NAME": "吴县"}, {"NAME": "长洲县"}],
    )
    gdf = boundaries(1820, level="xian", data_dir=tmp_path)
    assert set(gdf["NAME"]) == {"吴县", "长洲县"}
    assert gdf.attrs["chgis_year_filtered"] is False

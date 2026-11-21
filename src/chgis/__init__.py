"""Lightweight Python client for the CHGIS Temporal Gazetteer (TGAZ).

Historical China, 222 BCE-1911 CE: placename search, hierarchy queries,
a local SQLite cache, historical-boundary shapefile reading, a GB/T 2260
crosswalk, and gazetteer disambiguation.

The library ships no CHGIS data. The API is used live, or the local
``tgaz.db`` (downloaded by the user from Hugging Face) is queried
read-only, or CHGIS shapefiles the user downloaded are read from disk.
"""

from .boundaries import boundaries, list_available
from .cache import LocalCache, check_release, default_db_path, download_db
from .client import TGAZClient
from .crosswalk import Crosswalk, province_by_code, province_by_name, provinces
from .errors import ApiError, CacheError, ChgisError, DataNotAvailableError, NotFoundError
from .models import Place
from .resolve import ResolvedPlace, resolve

__version__ = "0.1.0"

__all__ = [
    "TGAZClient",
    "LocalCache",
    "Place",
    "ResolvedPlace",
    "resolve",
    "boundaries",
    "list_available",
    "Crosswalk",
    "provinces",
    "province_by_code",
    "province_by_name",
    "download_db",
    "check_release",
    "default_db_path",
    "ChgisError",
    "ApiError",
    "NotFoundError",
    "CacheError",
    "DataNotAvailableError",
    "__version__",
]

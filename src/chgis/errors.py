"""Errors raised by :mod:`chgis`."""


class ChgisError(Exception):
    """Base class for all errors raised by this library."""


class ApiError(ChgisError):
    """The TGAZ API returned an error, or the request failed."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class NotFoundError(ApiError):
    """The requested TGAZ record does not exist (HTTP 404)."""


class CacheError(ChgisError):
    """Something is wrong with the local SQLite cache (missing, corrupt,
    or the wrong schema)."""


class DataNotAvailableError(ChgisError):
    """The requested local data (e.g. CHGIS shapefiles for a year) is not
    present on disk. The library never ships CHGIS data; download it
    yourself and point the library at the directory (see README)."""

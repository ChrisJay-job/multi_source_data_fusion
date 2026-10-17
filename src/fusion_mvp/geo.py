from __future__ import annotations

from pyproj import Transformer


class LocalENU:
    """Horizontal ENU metres from a fixed WGS84 origin. Altitude is unused."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0 = lat0
        self.lon0 = lon0
        self._fwd = Transformer.from_crs(
            "EPSG:4326",
            f"+proj=tmerc +lat_0={lat0} +lon_0={lon0} +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs",
            always_xy=True,
        )
        self._inv = Transformer.from_crs(
            f"+proj=tmerc +lat_0={lat0} +lon_0={lon0} +k=1 +x_0=0 +y_0=0 +ellps=WGS84 +units=m +no_defs",
            "EPSG:4326",
            always_xy=True,
        )

    def to_xy(self, lat: float, lon: float) -> tuple[float, float]:
        x, y = self._fwd.transform(lon, lat)
        return float(x), float(y)

    def to_ll(self, x: float, y: float) -> tuple[float, float]:
        lon, lat = self._inv.transform(x, y)
        return float(lat), float(lon)

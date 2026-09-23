"""Terrain (30m DEM) loading, cropping, elevation lookup and LOS occlusion for Q3.

The DEM is the native geographic grid delivered as a .mat (EPSG:4326 cells,
~30 m = 1 arcsec).  We keep the *same* cell convention as Q2/prepare_data.py:
row 0 = north, col 0 = west, elevation constant per cell.  A cropped cache
(.npz) is written under results/ so downstream/validation runs do not need the
raw attachment.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy.io import loadmat

EPSG = 32649  # WGS84 / UTM zone 49N (local)


class Terrain:
    def __init__(self, z, west, north, dx, dy, nodata, inverse):
        self.z = np.asarray(z, dtype=np.float64)
        self.west = float(west)
        self.north = float(north)
        self.dx = float(dx)
        self.dy = float(dy)
        self.nodata = float(nodata)
        self.inverse = inverse
        self.nr, self.nc = self.z.shape

    @staticmethod
    def load_mat(dem_path: str | Path) -> "Terrain":
        data = loadmat(str(dem_path))
        z = data["dem"]
        dx, _, west, _, dy, north = data["transform"].ravel()
        nodata = float(data["nodata"].item())
        return Terrain(z, west, north, dx, dy, nodata,
                       Transformer.from_crs(EPSG, 4326, always_xy=True))

    @staticmethod
    def load_npz(cache_path: str | Path) -> "Terrain":
        d = np.load(str(cache_path))
        return Terrain(d["z"], float(d["west"]), float(d["north"]),
                       float(d["dx"]), float(d["dy"]), float(d["nodata"]),
                       Transformer.from_crs(EPSG, 4326, always_xy=True))

    def elevations(self, xs, ys) -> np.ndarray:
        """Nearest-cell terrain elevation (m) at UTM easting/northing arrays."""
        xs = np.asarray(xs, dtype=np.float64)
        ys = np.asarray(ys, dtype=np.float64)
        lon, lat = self.inverse.transform(xs, ys)
        col = np.floor((lon - self.west) / self.dx).astype(np.int64)
        row = np.floor((lat - self.north) / self.dy).astype(np.int64)
        if (col < 0).any() or (col >= self.nc).any() or (row < 0).any() or (row >= self.nr).any():
            raise ValueError("Point outside DEM coverage")
        return self.z[row, col]

    def elevation(self, x, y) -> float:
        return float(self.elevations(np.array([x]), np.array([y]))[0])

    def los_occluded(self, x1, y1, z1, x2, y2, z2,
                     spacing_m: float = 15.0, clearance_m: float = 0.0) -> bool:
        """True if terrain blocks the straight 3D sight line between two endpoints.

        Samples the horizontal projection at ~spacing_m (half the DEM cell) and
        compares terrain elevation against the linearly interpolated LOS height.
        Endpoints are excluded to avoid self-occlusion at the antenna cell.
        """
        d = float(np.hypot(x2 - x1, y2 - y1))
        n = max(3, int(np.ceil(d / max(spacing_m, 1e-6))) + 1)
        t = np.linspace(0.0, 1.0, n)
        xs = x1 + (x2 - x1) * t
        ys = y1 + (y2 - y1) * t
        zs = z1 + (z2 - z1) * t
        terr = self.elevations(xs[1:-1], ys[1:-1])
        return bool(np.any(terr >= zs[1:-1] - clearance_m))

    def los_occluded_batch(self, p, Q, spacing_m: float = 15.0, clearance_m: float = 0.0) -> np.ndarray:
        """Vectorized LOS for one fixed endpoint p=(x,y,z) against many q in Q=(N,3).

        Returns (N,) bool: sight line p->Q[j] occluded by terrain.  One pyproj
        transform per batch; interior samples only (endpoints excluded).
        """
        Q = np.asarray(Q, dtype=np.float64)
        N = Q.shape[0]
        if N == 0:
            return np.zeros(0, dtype=bool)
        px, py, pz = float(p[0]), float(p[1]), float(p[2])
        dx = Q[:, 0] - px
        dy = Q[:, 1] - py
        dz = Q[:, 2] - pz
        dist = np.hypot(dx, dy)
        ntot = np.maximum(3, np.ceil(dist / max(spacing_m, 1e-6)).astype(np.int64) + 1)
        cnt = ntot - 2  # interior sample count per line
        tot = int(cnt.sum())
        line_idx = np.repeat(np.arange(N), cnt)
        off = np.concatenate([[0], np.cumsum(cnt)[:-1]])
        within = np.arange(tot) - np.repeat(off, cnt)
        denom = (ntot[line_idx] - 1).astype(np.float64)
        t = (within + 1.0) / denom
        sx = px + dx[line_idx] * t
        sy = py + dy[line_idx] * t
        sz = pz + dz[line_idx] * t
        terr = self.elevations(sx, sy)
        occ = terr >= sz - clearance_m
        out = np.zeros(N, dtype=bool)
        np.logical_or.at(out, line_idx, occ)
        return out

    def hover_altitude(self, x, y, agl_m: float) -> float:
        return self.elevation(x, y) + agl_m

    def crop(self, xmin, xmax, ymin, ymax) -> "Terrain":
        lon = np.array([xmin, xmax, xmin, xmax])
        lat = np.array([ymin, ymin, ymax, ymax])
        lo, la = self.inverse.transform(lon, lat)
        c0 = int(np.floor((lo.min() - self.west) / self.dx))
        c1 = int(np.ceil((lo.max() - self.west) / self.dx)) + 1
        r0 = int(np.floor((la.max() - self.north) / self.dy))
        r1 = int(np.ceil((la.min() - self.north) / self.dy)) + 1
        c0 = max(0, c0); c1 = min(self.nc, c1)
        r0 = max(0, r0); r1 = min(self.nr, r1)
        west = self.west + c0 * self.dx
        north = self.north + r0 * self.dy
        return Terrain(self.z[r0:r1, c0:c1], west, north, self.dx, self.dy,
                       self.nodata, self.inverse)

    def save_npz(self, path: str | Path) -> None:
        np.savez_compressed(str(path), z=self.z, west=self.west, north=self.north,
                            dx=self.dx, dy=self.dy, nodata=self.nodata)


def node_bbox_utm(nodes) -> tuple[float, float, float, float]:
    xs = [n["x_m"] for n in nodes.values()]
    ys = [n["y_m"] for n in nodes.values()]
    return min(xs), max(xs), min(ys), max(ys)

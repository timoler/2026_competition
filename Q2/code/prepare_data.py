"""Read immutable original attachments and build portable Q2 inputs."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from openpyxl import load_workbook
from pyproj import Transformer
from scipy.io import loadmat
from scipy.optimize import brentq

from transport_core import write_csv, DEFAULT_RESULTS
from utm_interval import monotonic_signs


def source(root, name):
    found = list(root.rglob(name))
    if len(found) != 1:
        raise ValueError(f"Expected exactly one {name}: {found}")
    return found[0]


class Terrain:
    """Native geographic cells; intersect inverse-projected straight UTM lines."""

    def __init__(self, path):
        data = loadmat(path)
        self.z = data["dem"]
        self.dx, _, self.west, _, self.dy, self.north = data["transform"].ravel()
        self.nodata = float(data["nodata"].item())
        self.inverse = Transformer.from_crs(32649, 4326, always_xy=True)
        self.native_utm = True

    def grid(self, a, b, t):
        x = a[0] + (b[0] - a[0]) * np.asarray(t)
        y = a[1] + (b[1] - a[1]) * np.asarray(t)
        lon, lat = self.inverse.transform(x, y)
        return np.array([(lon - self.west) / self.dx,
                         (lat - self.north) / self.dy])

    def maximum(self, a, b):
        # Find every native grid-boundary crossing, not sampled elevations.
        # Whole-segment derivative intervals replace sampled monotonicity tests.
        if getattr(self, "native_utm", False):
            monotonic_signs(a, b)
        grid = self.grid(a, b, np.array([0., 1.]))
        roots = [0., 1.]
        for axis in range(2):
            values = grid[axis]
            lo, hi = sorted((values[0], values[-1]))
            for boundary in range(int(np.ceil(lo)), int(np.floor(hi)) + 1):
                fn = lambda t: float(self.grid(a, b, t)[axis] - boundary)
                if abs(fn(0)) < 1e-10:
                    roots.append(0.)
                elif abs(fn(1)) < 1e-10:
                    roots.append(1.)
                else:
                    roots.append(brentq(fn, 0., 1., xtol=1e-13))
        roots = np.unique(roots)
        probes = np.concatenate((roots, (roots[:-1] + roots[1:]) / 2))
        cells = set()
        for col, row in self.grid(a, b, probes).T:
            # Closed cells: all edge/corner contacts are included.
            cs = [int(np.floor(col))]
            rs = [int(np.floor(row))]
            if abs(col - round(col)) < 1e-7:
                cs = [int(round(col)) - 1, int(round(col))]
            if abs(row - round(row)) < 1e-7:
                rs = [int(round(row)) - 1, int(round(row))]
            cells.update((r, c) for r in rs for c in cs)
        nr, nc = self.z.shape
        if any(not (0 <= r < nr and 0 <= c < nc) for r, c in cells):
            raise ValueError("Path outside DEM coverage")
        elevations = np.array([self.z[r, c] for r, c in cells])
        if np.any(~np.isfinite(elevations)) or np.any(elevations == self.nodata):
            raise ValueError("Path intersects missing DEM")
        return float(elevations.max()), len(cells)


def prepare(root, out):
    names = ["调度中心与服务区.xlsx", "运输无人机数据.xlsx",
             "物资需求与配送时限.xlsx", "镇龙乡及周边30米DEM.mat",
             "山区洪涝灾害下无人机运输与通信协同优化.docx"]
    files = {name: source(root, name) for name in names}
    manifest = [dict(file_name=p.name, source_relative_path=p.relative_to(root).as_posix(),
                     size_bytes=p.stat().st_size,
                     sha256=hashlib.sha256(p.read_bytes()).hexdigest())
                for p in files.values()]
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "q2_input_manifest.csv", manifest)
    project = Transformer.from_crs(4326, 32649, always_xy=True)
    rows = list(load_workbook(files[names[0]], data_only=True)["数据"].values)
    nodes = {}
    for row in rows:
        if not isinstance(row[0], str) or not (row[0] == "O01" or row[0].startswith("S0")):
            continue
        ident, _, lon, lat, ground = row[:5]
        x, y = project.transform(lon, lat)
        nodes[ident] = dict(node_id=ident, lon=lon, lat=lat, ground_m=ground,
                           work_m=ground + (0 if ident == "O01" else 30), x_m=x, y_m=y)
    assert len(nodes) == 16
    rows = list(load_workbook(files[names[1]], data_only=True)["数据"].values)
    keys = ["type_id", "name", "empty_kg", "capacity_kg", "capacity_m3",
            "cruise_mps", "empty_range_m", "full_range_m", "energy_kwh",
            "reserve", "prep_s", "load_box_s", "handover_base_s",
            "handover_box_s", "ascent_mps", "descent_mps", "ascent_efficiency",
            "descent_efficiency"]
    types = {}
    for row in rows[2:5]:
        obj = dict(zip(keys, row))
        obj["reserve"] /= 100
        types[obj["type_id"]] = obj
    drones = {r[0]: r[1] for r in rows[8:16]}
    batteries = {}
    for typ, count, full, *_ in rows[19:22]:
        types[typ]["full_charge_s"] = full
        for i in range(count):
            batteries[f"BAT-{typ}-{i+1:02d}"] = typ
    wb = load_workbook(files[names[2]], data_only=True)
    boxes = {}
    for row in list(wb["逐箱货箱清单"].values)[1:]:
        if not row[0]:
            continue
        ident, dest, kind, mass, volume, first, due1, due, priority = row
        hard = min([float(x) for x in
                    [due1 if first == "是" else None,
                     due if kind == "医疗物资" else None] if x is not None],
                   default=None)
        if ident in boxes:
            raise ValueError(f"Duplicate box {ident}")
        boxes[ident] = dict(box_id=ident, destination=dest, category=kind,
                           mass_kg=mass, volume_m3=volume, first=first == "是",
                           hard_due_s=hard, desired_due_s=due, priority=priority)
    assert len(boxes) == 80 and len(drones) == 8 and len(batteries) == 14
    for row in list(wb["数据"].values)[1:]:
        if not row[0]:
            continue
        dest, kind, count, first_count, mass, vol, *_ = row
        subset = [b for b in boxes.values() if b["destination"] == dest and b["category"] == kind]
        assert len(subset) == count
        assert sum(b["first"] for b in subset) == first_count
        assert all(b["mass_kg"] == mass and b["volume_m3"] == vol for b in subset)
    terrain = Terrain(files[names[3]])
    geometries = {}
    for i, a in nodes.items():
        for j, b in nodes.items():
            if i >= j:
                continue
            peak, count = terrain.maximum((a["x_m"], a["y_m"]), (b["x_m"], b["y_m"]))
            d = float(np.hypot(b["x_m"] - a["x_m"], b["y_m"] - a["y_m"]))
            for start, end in [(i, j), (j, i)]:
                ascent = peak + 50 - nodes[start]["work_m"]
                descent = peak + 50 - nodes[end]["work_m"]
                if min(ascent, descent) < 0:
                    raise ValueError("Negative stage height; resolve altitude source")
                geometries[start + "|" + end] = dict(
                    origin=start, destination=end, distance_m=d, terrain_max_m=peak,
                    cruise_altitude_m=peak + 50, ascent_m=ascent, descent_m=descent,
                    cell_count=count)
    data = dict(nodes=nodes, types=types, drones=drones, batteries=batteries,
                boxes=boxes, geometry=geometries, crs="EPSG:32649", source_manifest=manifest)
    (out / "q2_inputs.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(out / "q2_geometry.csv", list(geometries.values()))
    write_csv(out / "q2_nodes.csv", list(nodes.values()))
    write_csv(out / "q2_boxes.csv", list(boxes.values()))
    write_csv(out / "q2_types.csv", list(types.values()))
    print(f"Prepared {len(boxes)} boxes and {len(geometries)} directed segments")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    prepare(args.source_root, args.output)

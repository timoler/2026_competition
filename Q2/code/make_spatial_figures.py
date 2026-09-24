"""Q2 空间可视化图：全局运输航迹网络 + 典型多点配送架次路径（只读生成）。

数据来源（全部为已发布的正式结果，脚本不写入、不修改任何 CSV/JSON）：
  - Q2/results/q2_trips.csv          架次、机型、无人机、完整访问路线
  - Q2/results/q2_segments.csv       逐航段两端 UTM 坐标（航迹折线的真实来源）
  - Q2/results/q2_deliveries.csv     逐箱到达时刻、质量、品类
  - Q2/results/q2_nodes.csv          16 个节点的 UTM 坐标
  - Q3/results/q3_terrain_cache.npz  30 m DEM 裁剪缓存（经 Q3/audit/terrain_source_check.json
                                     核验为原始附件 DEM 的原生精确子集，行列偏移 421/381）

地形底图复用 Q3/code/terrain.py 的 Terrain 加载器，与 Q3 视线遮挡判定使用同一份
地形数据与同一套 UTM(EPSG:32649) → 经纬度换算，避免出现第二套地形口径。

输出（论文图统一目录 paper_figures/）：
  - paper_figures/q2_transport_routes_final.png
  - paper_figures/q2_multistop_route_final.png
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
from matplotlib.colors import LinearSegmentedColormap
from pyproj import Transformer

CODE = Path(__file__).resolve().parent
REPO = CODE.parents[1]
R = REPO / "Q2" / "results"
FIG = REPO / "paper_figures"   # 论文图统一目录（本仓库唯一论文图入口）
FIG.mkdir(parents=True, exist_ok=True)

# 地形：复用 Q3 已验证的 DEM 缓存与加载器（同一份附件 DEM，同一套坐标换算）
sys.path.insert(0, str(REPO / "Q3" / "code"))
from config import TERRAIN_CACHE  # noqa: E402
from terrain import Terrain  # noqa: E402

BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#d03b3b"
INK, MUTED, GRID = "#0b0b0b", "#898781", "#e1e0d9"
TYPE_COLOR = {"A": BLUE, "B": ORANGE, "C": AQUA}
TYPE_LABEL = {"A": "A 型", "B": "B 型", "C": "C 型"}

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
    "axes.unicode_minus": False,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK,
    "xtick.color": MUTED, "ytick.color": MUTED,
    "font.size": 10, "savefig.dpi": 300,
})


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


GRAY_RAMP = LinearSegmentedColormap.from_list(
    "terrain_gray", ["#ffffff", "#e9e7df", "#cbc8bc", "#a5a196"])
_TO_UTM = Transformer.from_crs(4326, 32649, always_xy=True)  # WGS84 → UTM 49N


def utm_ticks(ax):
    """显示完整 UTM 数值，避免 1e6 偏移量记法。"""
    from matplotlib.ticker import MaxNLocator, ScalarFormatter
    for axis, n in ((ax.xaxis, 6), (ax.yaxis, 5)):
        axis.set_major_locator(MaxNLocator(n))
        fmt = ScalarFormatter(useOffset=False)
        fmt.set_scientific(False)
        axis.set_major_formatter(fmt)


def terrain_background(ax, alpha=0.95, hillshade_weight=0.62):
    """高程色阶 + 晕渲的浅灰地形底图（单色系，不使用彩虹配色、不画等高线）。

    高程与晕渲值全部来自 30 m DEM 缓存，不做任何平滑或虚构。
    """
    terr = Terrain.load_npz(TERRAIN_CACHE)
    z = np.array(terr.z, dtype=np.float64)
    z[z <= terr.nodata + 1.0] = np.nan
    zfill = np.nan_to_num(z, nan=float(np.nanmean(z)))
    zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))

    # 晕渲：光源方位角 315°、高度角 45°，按格网边长 30 m 求梯度
    gy, gx = np.gradient(zfill, 30.0, 30.0)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.deg2rad(315.0), np.deg2rad(45.0)
    hs = np.clip(np.sin(alt) * np.sin(slope)
                 + np.cos(alt) * np.cos(slope) * np.cos(az - aspect), 0.0, 1.0)

    # 色阶（高程归一化）与晕渲合成：值越大 → 颜色越深
    norm = (zfill - zmin) / max(zmax - zmin, 1e-9)
    val = (1.0 - hillshade_weight) * norm + hillshade_weight * (1.0 - hs)

    # pcolormesh 需要格网边界坐标，避免把格网中心当作单元中心
    nr, nc = z.shape
    lon_e = terr.west + np.arange(nc + 1) * terr.dx
    lat_e = terr.north + np.arange(nr + 1) * terr.dy
    lonE, latE = np.meshgrid(lon_e, lat_e)
    xe, ye = _TO_UTM.transform(lonE, latE)  # DEM 为经纬度格网，转成 UTM 才能与航迹同轴

    ax.pcolormesh(xe, ye, val, cmap=GRAY_RAMP, vmin=0.0, vmax=1.0, alpha=alpha,
                  shading="flat", zorder=0, rasterized=True)
    ax.set_aspect("equal")
    ax.grid(color=GRID, linewidth=0.6, alpha=0.5)
    return terr, (zmin, zmax)


def set_view(ax, nodes, margin=0.12):
    """视野取 16 个节点的外包框外扩 margin，地形底图自然溢出裁切。"""
    xs = [p[0] for p in nodes.values()]
    ys = [p[1] for p in nodes.values()]
    mx = (max(xs) - min(xs)) * margin
    my = (max(ys) - min(ys)) * margin
    ax.set_xlim(min(xs) - mx, max(xs) + mx)
    ax.set_ylim(min(ys) - my, max(ys) + my)


def load_plan():
    """返回节点坐标、逐架次航迹折线、逐架次货箱明细。"""
    nodes = {r["node_id"]: (float(r["x_m"]), float(r["y_m"]))
             for r in read_csv(R / "q2_nodes.csv")}
    trips = {r["trip_id"]: r for r in read_csv(R / "q2_trips.csv")}

    segs = defaultdict(list)
    for r in read_csv(R / "q2_segments.csv"):
        segs[r["trip_id"]].append(r)
    paths = {}
    for tid, ss in segs.items():
        ss.sort(key=lambda r: int(r["segment_id"]))
        pts = [(float(r["origin_x_m"]), float(r["origin_y_m"])) for r in ss]
        pts.append((float(ss[-1]["destination_x_m"]), float(ss[-1]["destination_y_m"])))
        paths[tid] = pts

    deliv = defaultdict(list)
    for r in read_csv(R / "q2_deliveries.csv"):
        deliv[r["trip_id"]].append(r)
    return nodes, trips, paths, deliv


def draw_nodes(ax, nodes, label_size=6.5, show_service_labels=True, skip_labels=()):
    for nid, (x, y) in sorted(nodes.items()):
        if nid == "O01":
            continue
        ax.plot(x, y, "o", color="#5b5a55", ms=3.2, zorder=4)
        if show_service_labels and nid not in skip_labels:
            ax.annotate(nid, (x, y), textcoords="offset points", xytext=(3.5, 3.0),
                        fontsize=label_size, color="#5b5a55", zorder=5)
    ox, oy = nodes["O01"]
    ax.plot(ox, oy, "*", color=RED, ms=17, zorder=6,
            markeredgecolor="white", markeredgewidth=0.7)
    ax.annotate("O01 调度中心\n（G01 通信网关）", (ox, oy), textcoords="offset points",
                xytext=(7, -13), fontsize=8, color=RED, zorder=6, linespacing=1.35)


# ---------------------------------------------------------------------------
# 图5：Q2 全局运输航迹空间分布
# ---------------------------------------------------------------------------
def fig5():
    nodes, trips, paths, _ = load_plan()
    by_type = defaultdict(int)
    for t in trips.values():
        by_type[t["type_id"]] += 1

    fig, ax = plt.subplots(figsize=(10.2, 7.6))
    terrain_background(ax)
    set_view(ax, nodes)
    utm_ticks(ax)

    for tid in sorted(paths):
        pts = np.array(paths[tid])
        ax.plot(pts[:, 0], pts[:, 1], "-", color=TYPE_COLOR[trips[tid]["type_id"]],
                lw=1.25, alpha=0.45, solid_capstyle="round", zorder=2)

    draw_nodes(ax, nodes)
    ax.set_xlabel("UTM 东向坐标 x (m)")
    ax.set_ylabel("UTM 北向坐标 y (m)")

    handles = [plt.Line2D([], [], color=TYPE_COLOR[k], lw=2.0,
                          label=f"{TYPE_LABEL[k]}无人机航迹（{by_type[k]} 架次）")
               for k in ("A", "B", "C")]
    handles += [plt.Line2D([], [], color=RED, marker="*", lw=0, ms=12, label="O01 调度中心（G01 网关）"),
                plt.Line2D([], [], color="#5b5a55", marker="o", lw=0, ms=4, label="服务区 S001–S015")]
    ax.legend(handles=handles, loc="upper left", frameon=False, fontsize=8.5,
              labelspacing=0.55)
    fig.tight_layout()
    fig.savefig(FIG / "q2_transport_routes_final.png", dpi=300)
    plt.close(fig)
    print(f"q2_transport_routes_final.png: {len(paths)} 架次，"
          f"A/B/C = {by_type['A']}/{by_type['B']}/{by_type['C']}")


# ---------------------------------------------------------------------------
# 图6：典型多点配送架次路径
# ---------------------------------------------------------------------------
def pick_multistop(trips, paths):
    """自动选取代表性多点架次：先比访问服务区数，再比单程航程。"""
    best = None
    for tid, t in trips.items():
        stops = [s for s in t["route"].split("-") if s not in ("", "O01")]
        if len(stops) < 2:
            continue
        # 去程（O01 → 各服务点）的真实航程：O01 到最远服务点之前的所有航段
        one_way = sum(np.hypot(paths[tid][i + 1][0] - paths[tid][i][0],
                               paths[tid][i + 1][1] - paths[tid][i][1])
                      for i in range(len(stops)))
        key = (len(stops), one_way)
        if best is None or key > best[0]:
            best = (key, tid, stops, one_way)
    return best


def fig6():
    nodes, trips, paths, deliv = load_plan()
    key, tid, stops, seg_len = pick_multistop(trips, paths)
    t = trips[tid]

    fig, ax = plt.subplots(figsize=(10.0, 7.6))
    terrain_background(ax)
    set_view(ax, nodes)
    utm_ticks(ax)

    # 背景：其余节点与全部航迹（浅色）提供空间参照
    for other in sorted(paths):
        if other == tid:
            continue
        pts = np.array(paths[other])
        ax.plot(pts[:, 0], pts[:, 1], "-", color="#a9a8a1", lw=0.7, alpha=0.30, zorder=1)
    stop_sites = {r["destination"] for r in deliv[tid]}
    draw_nodes(ax, nodes, show_service_labels=True, skip_labels=stop_sites)

    pts = np.array(paths[tid])
    color = TYPE_COLOR[t["type_id"]]
    ax.plot(pts[:, 0], pts[:, 1], "-", color=color, lw=2.4, alpha=0.95, zorder=4,
            solid_capstyle="round")

    # 方向箭头（每段中点）
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        ax.annotate("", xy=(x0 + (x1 - x0) * 0.58, y0 + (y1 - y0) * 0.58),
                    xytext=(x0 + (x1 - x0) * 0.42, y0 + (y1 - y0) * 0.42),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=1.8,
                                    mutation_scale=16), zorder=5)

    # 各服务点：访问顺序 + 该站货箱
    mark = "①②③④⑤⑥⑦⑧⑨"
    order = []
    for r in deliv[tid]:
        if r["destination"] not in [o[0] for o in order]:
            order.append((r["destination"], float(r["arrival_s"])))
    order.sort(key=lambda o: o[1])
    for i, (site, arr) in enumerate(order):
        boxes = [r for r in deliv[tid] if r["destination"] == site]
        mass = sum(float(r["mass_kg"]) for r in boxes)
        cats = "、".join(sorted({r["category"] for r in boxes}))
        x, y = nodes[site]
        ax.plot(x, y, "o", color=color, ms=11, markeredgecolor="white",
                markeredgewidth=1.4, zorder=6)
        ax.annotate(f"{mark[i]} {site}　{arr:.0f} s\n{cats} {mass:.0f} kg（{len(boxes)} 箱）",
                    (x, y), textcoords="offset points", xytext=(13, -4),
                    fontsize=8.5, color=INK, zorder=7, linespacing=1.45)

    ax.set_xlabel("UTM 东向坐标 x (m)")
    ax.set_ylabel("UTM 北向坐标 y (m)")
    ax.legend(handles=[
        plt.Line2D([], [], color=color, lw=2.4,
                   label=f"架次 {tid}（{TYPE_LABEL[t['type_id']]}，{t['drone_id']}）"),
        plt.Line2D([], [], color="#a9a8a1", lw=1.2, alpha=0.6, label="其余架次航迹（背景）"),
        plt.Line2D([], [], color=RED, marker="*", lw=0, ms=12, label="O01 调度中心（G01 网关）"),
    ], loc="lower left", frameon=False, fontsize=8.5)
    fig.tight_layout()
    fig.savefig(FIG / "q2_multistop_route_final.png", dpi=300)
    plt.close(fig)
    print(f"q2_multistop_route_final.png: 选中 {tid} "
          f"{t['route']}（{len(order)} 个服务点）")


if __name__ == "__main__":
    fig5()
    fig6()
    print("Q2 spatial figures written")

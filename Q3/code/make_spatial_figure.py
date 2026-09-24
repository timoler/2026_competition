"""Q3 运输—中继协同空间部署图（真实三维地形 + 运输航迹 + 中继悬停部署）。

只读生成，不修改任何模型、调度方案或正式 CSV/JSON。

数据来源（全部为正式结果 / 题目附件）：
  - Q3/results/q3_relay_schedule.csv       3 个中继架次的真实悬停三维坐标
                                           (hover_x_m, hover_y_m, hover_altitude_m, agl_m)
  - Q3/results/q3_transport_schedule.csv   26 个运输架次（本图只取架次号与机型）
  - Q3/results/q3_communication_links.csv  逐秒链路归属（provider=S01/S02/S03 或 G01）
  - Q2/results/q2_segments.csv             逐航段两端 UTM 坐标、作业海拔、巡航海拔、四个阶段时刻
  - Q2/results/q2_nodes.csv                节点 UTM 坐标
  - Q3/results/q3_terrain_cache.npz        30 m DEM（附件原生素材，见 terrain_source_check.json）

三维航迹由 q2_segments.csv 的爬升—巡航—下降分段几何精确重建：
每个航段为「在起点垂直爬升到巡航海拔 → 水平巡航到终点 → 在终点垂直下降到作业海拔」。
该重建已与 Q2 权威轨迹接口 transport_core.Trajectory 逐架次逐时刻比对，
最大偏差 2e-9 m（见文件末尾的 --check 自检）。

中继—运输机接入链路：对每个 (架次, 中继架次) 组合，取该中继实际服务该架次的时间窗
中点，用权威轨迹接口取运输机真实三维位置，再与中继真实悬停点连线。
链路关系全部来自 q3_communication_links.csv，不虚构任何覆盖圆或连接。

输出：
  - Q3/figures/q3_fig4_transport_relay_spatial.png      三维真实地形版本
  - Q3/figures/q3_fig4_transport_relay_spatial_2d.png   平面版本（供论文择优选用）
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LightSource, LinearSegmentedColormap
from matplotlib.lines import Line2D
from pyproj import Transformer
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (注册 3d 投影)

CODE = Path(__file__).resolve().parent
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from config import Q2_RESULTS, RESULTS, FIGURES, TERRAIN_CACHE  # noqa: E402
from terrain import Terrain  # noqa: E402
from trajectory import TransportTrajectory  # noqa: E402

BLUE, ORANGE, AQUA, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#4a3aa7"
RED, GRAY, INK, MUTED, GRID = "#d03b3b", "#898781", "#0b0b0b", "#898781", "#e1e0d9"

# 与 q3_joint_timeline_final.png 完全一致的保障配色，便于两图对读
PROVIDER_COLOR = {"R01": BLUE, "R02": ORANGE}
LINK_COLOR = {"R01": BLUE, "R02": ORANGE}
TERRAIN_TINT = LinearSegmentedColormap.from_list(
    "terrain_tint", ["#ffffff", "#eeece5", "#d5d2c7", "#b3afa4"])

_TO_UTM = Transformer.from_crs(4326, 32649, always_xy=True)  # WGS84 → UTM 49N

Z_EXAGGERATION = 4.0  # z 轴视觉放大倍数（坐标数值为真实高程，单位 m）

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


# ---------------------------------------------------------------------------
# 数据装配
# ---------------------------------------------------------------------------
def load():
    nodes = {r["node_id"]: (float(r["x_m"]), float(r["y_m"]))
             for r in read_csv(Q2_RESULTS / "q2_nodes.csv")}

    segs = defaultdict(list)
    for r in read_csv(Q2_RESULTS / "q2_segments.csv"):
        segs[r["trip_id"]].append(r)

    # 逐架次时间—位置剖面：每个航段 4 个折点，段内各阶段匀速，故线性插值即精确解
    profiles = {}
    for tid, ss in segs.items():
        ss.sort(key=lambda r: int(r["segment_id"]))
        pts = []
        for s in ss:
            x0, y0 = float(s["origin_x_m"]), float(s["origin_y_m"])
            z0 = float(s["origin_work_altitude_m"])
            x1, y1 = float(s["destination_x_m"]), float(s["destination_y_m"])
            z1 = float(s["destination_work_altitude_m"])
            zc = float(s["cruise_altitude_m"])
            for t, p in ((float(s["ascent_start_s"]), (x0, y0, z0)),
                         (float(s["ascent_end_s"]), (x0, y0, zc)),
                         (float(s["cruise_end_s"]), (x1, y1, zc)),
                         (float(s["descent_end_s"]), (x1, y1, z1))):
                if pts and abs(t - pts[-1][0]) < 1e-9:
                    pts[-1] = (t, p)
                else:
                    pts.append((t, p))
        profiles[tid] = (np.array([p[0] for p in pts]),
                         np.array([p[1] for p in pts]))

    trips = {r["trip_id"]: r for r in read_csv(RESULTS / "q3_transport_schedule.csv")}

    sorties = {}
    for r in read_csv(RESULTS / "q3_relay_schedule.csv"):
        sorties[r["sortie_id"]] = dict(
            relay_id=r["relay_id"],
            x=float(r["hover_x_m"]), y=float(r["hover_y_m"]),
            z=float(r["hover_altitude_m"]), agl=float(r["agl_m"]),
            t0=float(r["service_start_s"]), t1=float(r["service_end_s"]),
            energy=float(r["energy_kwh"]), soc=float(r["return_soc"]))

    # 逐秒链路归属 → (架次, 中继架次) 的实际服务时间窗
    win = defaultdict(lambda: [np.inf, -np.inf])
    for r in read_csv(RESULTS / "q3_communication_links.csv"):
        p = r["provider"]
        if p == "G01":
            continue
        t = float(r["time_s"])
        k = (r["trip_id"], p)
        win[k][0] = min(win[k][0], t)
        win[k][1] = max(win[k][1], t)

    prov = defaultdict(set)
    for (tid, sid) in win:
        prov[tid].add(sid)
    return nodes, trips, profiles, sorties, win, prov


def link_color(sids):
    r = {sorties_relay[s] for s in sids}
    if r == {"R01"}:
        return BLUE
    if r == {"R02"}:
        return ORANGE
    return VIOLET


sorties_relay = {}


def pos_at(profiles, tid, t):
    ts, xyz = profiles[tid]
    return np.array([np.interp(t, ts, xyz[:, i]) for i in range(3)])


def consistency_check(nodes, profiles, sorties, win):
    """三维航迹重建与 Q2 权威轨迹接口的逐点比对（只打印，不改数据）。"""
    tj = TransportTrajectory(Q2_RESULTS)
    worst = 0.0
    for tid, (ts, xyz) in profiles.items():
        for t in np.linspace(ts[0], ts[-1], 25):
            e = tj.position(tid, float(t))
            p = pos_at(profiles, tid, float(t))
            worst = max(worst, abs(p[0] - e["x"]), abs(p[1] - e["y"]),
                        abs(p[2] - e["altitude_m"]))
    return worst


# ---------------------------------------------------------------------------
# 地形
# ---------------------------------------------------------------------------
def cropped_terrain(nodes, margin=0.06):
    xs = [p[0] for p in nodes.values()]
    ys = [p[1] for p in nodes.values()]
    mx = (max(xs) - min(xs)) * margin
    my = (max(ys) - min(ys)) * margin
    terr = Terrain.load_npz(TERRAIN_CACHE)
    return terr.crop(min(xs) - mx, max(xs) + mx, min(ys) - my, max(ys) + my)


def surface_rgb(terr, step):
    z = np.array(terr.z, dtype=np.float64)[::step, ::step]
    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(z, cmap=TERRAIN_TINT, vert_exag=1.0,
                   dx=terr.dx * 111320 * np.cos(np.deg2rad(23.0)) * step,
                   dy=abs(terr.dy) * 110540 * step, blend_mode="soft")
    return z, rgb


def set_utm_ticks(ax):
    from matplotlib.ticker import MaxNLocator, ScalarFormatter
    for axis, n in ((ax.xaxis, 5), (ax.yaxis, 5)):
        axis.set_major_locator(MaxNLocator(n))
        fmt = ScalarFormatter(useOffset=False)
        fmt.set_scientific(False)
        axis.set_major_formatter(fmt)


# ---------------------------------------------------------------------------
# 三维图
# ---------------------------------------------------------------------------
def fig3d(nodes, trips, profiles, sorties, win, prov, terr):
    fig = plt.figure(figsize=(13.0, 6.9))
    ax = fig.add_axes([0.185, 0.00, 0.80, 1.00], projection="3d")
    ax.set_facecolor("white")

    step = 3
    z, rgb = surface_rgb(terr, step)
    nr, nc = z.shape
    lon_e = terr.west + np.arange(nc) * terr.dx * step
    lat_e = terr.north + np.arange(nr) * terr.dy * step
    lonE, latE = np.meshgrid(lon_e, lat_e)
    XE, YE = _TO_UTM.transform(lonE, latE)
    ax.plot_surface(XE, YE, z, facecolors=rgb, rstride=1, cstride=1,
                    linewidth=0, antialiased=False, shade=False, alpha=0.98)

    # 运输航迹（真实三维，含垂直爬升/下降段）
    for tid in sorted(profiles):
        ts, xyz = profiles[tid]
        c = link_color(prov.get(tid, set())) if prov.get(tid) else GRAY
        ax.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], color=c, lw=1.1,
                alpha=0.9 if prov.get(tid) else 0.55, zorder=3)

    # 中继悬停点 + 到地面的垂线（真实几何关系）
    for sid, s in sorted(sorties.items()):
        c = PROVIDER_COLOR[s["relay_id"]]
        ax.plot([s["x"]], [s["y"]], [s["z"]], marker="^", color=c, ms=11,
                markeredgecolor="white", markeredgewidth=1.0, zorder=8)
        gz = float(terr.elevation(s["x"], s["y"]))
        ax.plot([s["x"], s["x"]], [s["y"], s["y"]], [gz, s["z"]],
                color=c, lw=0.8, ls=":", alpha=0.75, zorder=5)
        ax.text(s["x"], s["y"], s["z"] + 60,
                f"{sid}／{s['relay_id']}　悬停 {s['z']:.0f} m",
                fontsize=8, color=c, ha="center", zorder=9)

    # 回传链路：G01（O01，天线高 20 m）→ 中继悬停点
    ox, oy = nodes["O01"]
    g01_z = 127.7 + 20.0  # 附件 O01 地面高程 127.7 m + 场景给定 G01 天线高 20 m
    for sid, s in sorted(sorties.items()):
        ax.plot([ox, s["x"]], [oy, s["y"]], [g01_z, s["z"]],
                color=PROVIDER_COLOR[s["relay_id"]], lw=1.3, ls="--",
                alpha=0.8, zorder=6)

    # 接入链路：中继 → 该中继服务该架次时间窗中点的运输机真实三维位置
    tj = TransportTrajectory(Q2_RESULTS)
    for (tid, sid), (t0, t1) in sorted(win.items()):
        s = sorties[sid]
        e = tj.position(tid, float((t0 + t1) / 2.0))
        ax.plot([s["x"], e["x"]], [s["y"], e["y"]], [s["z"], e["altitude_m"]],
                color=LINK_COLOR[s["relay_id"]], lw=0.7, alpha=0.55, zorder=4)

    for nid, (x, y) in sorted(nodes.items()):
        if nid == "O01":
            continue
        ax.text(x, y, float(terr.elevation(x, y)) + 40, nid, fontsize=6,
                color="#6a6862", ha="center", zorder=7)
    ax.plot([ox], [oy], [g01_z], marker="*", color=RED, ms=16, zorder=10,
            markeredgecolor="white", markeredgewidth=0.8)
    ax.text(ox - 520, oy - 1500, g01_z + 90, "O01／G01", fontsize=9.5, color=RED,
            ha="center", zorder=11)

    xs = [p[0] for p in nodes.values()]
    ys = [p[1] for p in nodes.values()]
    dx, dy = (max(xs) - min(xs)) * 0.07, (max(ys) - min(ys)) * 0.07
    ax.set_xlim(min(xs) - dx, max(xs) + dx)
    ax.set_ylim(min(ys) - dy, max(ys) + dy)
    zmin = float(np.nanmin(terr.z))
    zmax = max(s["z"] for s in sorties.values())
    ax.set_zlim(zmin, zmax + 60)
    ax.set_box_aspect(((max(xs) - min(xs)) * 1.14, (max(ys) - min(ys)) * 1.14,
                       (zmax - zmin) * Z_EXAGGERATION))

    ax.set_xlabel("UTM 东向 x (m)", labelpad=8)
    ax.set_ylabel("UTM 北向 y (m)", labelpad=8)
    ax.set_zlabel(f"真实高程 (m)　［z 轴视觉放大 {Z_EXAGGERATION:.0f}×］", labelpad=6)
    set_utm_ticks(ax)
    ax.view_init(elev=24, azim=-62)
    ax.grid(alpha=0.25)

    handles = [
        Line2D([], [], color=BLUE, lw=2, label="R01 保障架次航迹"),
        Line2D([], [], color=ORANGE, lw=2, label="R02 保障架次航迹"),
        Line2D([], [], color=VIOLET, lw=2, label="R01+R02 保障架次航迹"),
        Line2D([], [], color=GRAY, lw=2, alpha=0.6, label="直连 G01 架次航迹"),
        Line2D([], [], color=BLUE, marker="^", lw=0, ms=9, label="中继悬停点（AGL 均 300 m）"),
        Line2D([], [], color=MUTED, lw=1.2, ls="--", label="回传链路（中继 → G01）"),
        Line2D([], [], color=MUTED, lw=0.8, label="接入链路（运输机 → 中继）"),
        Line2D([], [], color=RED, marker="*", lw=0, ms=12, label="O01 调度中心／G01 网关"),
    ]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.005, 0.995),
               frameon=False, fontsize=8.5, labelspacing=0.5)
    fig.savefig(FIGURES / "q3_fig4_transport_relay_spatial.png", dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 二维图（平面部署）
# ---------------------------------------------------------------------------
def fig2d(nodes, trips, profiles, sorties, win, prov, terr):
    GRAY_RAMP = TERRAIN_TINT
    fig, ax = plt.subplots(figsize=(10.6, 7.8))

    z = np.array(terr.z, dtype=np.float64)
    zfill = np.nan_to_num(z, nan=float(np.nanmean(z)))
    zmin, zmax = float(np.nanmin(z)), float(np.nanmax(z))
    gy, gx = np.gradient(zfill, 30.0, 30.0)
    slope = np.pi / 2.0 - np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    az, alt = np.deg2rad(315.0), np.deg2rad(45.0)
    hs = np.clip(np.sin(alt) * np.sin(slope)
                 + np.cos(alt) * np.cos(slope) * np.cos(az - aspect), 0.0, 1.0)
    norm = (zfill - zmin) / max(zmax - zmin, 1e-9)
    val = 0.38 * norm + 0.62 * (1.0 - hs)

    nr, nc = z.shape
    lonE, latE = np.meshgrid(terr.west + np.arange(nc + 1) * terr.dx,
                             terr.north + np.arange(nr + 1) * terr.dy)
    xe, ye = _TO_UTM.transform(lonE, latE)
    ax.pcolormesh(xe, ye, val, cmap=GRAY_RAMP, vmin=0.0, vmax=1.0, alpha=0.95,
                  shading="flat", zorder=0, rasterized=True)

    for tid in sorted(profiles):
        ts, xyz = profiles[tid]
        if prov.get(tid):
            continue
        ax.plot(xyz[:, 0], xyz[:, 1], color="#6f6d68", lw=1.2, alpha=0.6, zorder=2)
    for tid in sorted(profiles):
        ts, xyz = profiles[tid]
        if not prov.get(tid):
            continue
        ax.plot(xyz[:, 0], xyz[:, 1], color=link_color(prov[tid]), lw=1.6,
                alpha=0.9, zorder=3, solid_capstyle="round")

    ox, oy = nodes["O01"]
    tj = TransportTrajectory(Q2_RESULTS)
    for sid, s in sorted(sorties.items()):
        c = PROVIDER_COLOR[s["relay_id"]]
        for (tid, s2), (t0, t1) in win.items():
            if s2 != sid:
                continue
            e = tj.position(tid, float((t0 + t1) / 2.0))
            ax.plot([s["x"], e["x"]], [s["y"], e["y"]], color=c, lw=0.7,
                    alpha=0.5, zorder=4)
        ax.plot([ox, s["x"]], [oy, s["y"]], color=c, lw=1.4, ls="--",
                alpha=0.85, zorder=5)
        ax.plot(s["x"], s["y"], marker="^", color=c, ms=12, zorder=7,
                markeredgecolor="white", markeredgewidth=1.1)
        ax.annotate(f"{sid}／{s['relay_id']}\n悬停 {s['z']:.0f} m",
                    (s["x"], s["y"]), textcoords="offset points", xytext=(9, 7),
                    fontsize=8, color=c, zorder=8, linespacing=1.4)

    for nid, (x, y) in sorted(nodes.items()):
        if nid == "O01":
            continue
        ax.plot(x, y, "o", color="#5b5a55", ms=3.2, zorder=6)
        ax.annotate(nid, (x, y), textcoords="offset points", xytext=(3.5, 3.0),
                    fontsize=6.5, color="#5b5a55", zorder=7)
    ax.plot(ox, oy, "*", color=RED, ms=17, zorder=9,
            markeredgecolor="white", markeredgewidth=0.8)
    ax.annotate("O01 调度中心\n（G01 通信网关）", (ox, oy), textcoords="offset points",
                xytext=(0, -26), ha="center", va="top", fontsize=8, color=RED,
                zorder=9, linespacing=1.35)

    ax.set_xlim(xe.min(), xe.max())
    ax.set_ylim(ye.min(), ye.max())
    ax.set_aspect("equal")
    ax.grid(color=GRID, linewidth=0.6, alpha=0.5)
    set_utm_ticks(ax)
    ax.set_xlabel("UTM 东向坐标 x (m)")
    ax.set_ylabel("UTM 北向坐标 y (m)")

    handles = [
        Line2D([], [], color=BLUE, lw=1.8, label="R01 保障架次航迹"),
        Line2D([], [], color=ORANGE, lw=1.8, label="R02 保障架次航迹"),
        Line2D([], [], color=VIOLET, lw=1.8, label="R01+R02 保障架次航迹"),
        Line2D([], [], color="#6f6d68", lw=1.2, alpha=0.7, label="直连 G01 架次航迹"),
        Line2D([], [], color=BLUE, marker="^", lw=0, ms=9, label="中继悬停点（AGL 均 300 m）"),
        Line2D([], [], color=MUTED, lw=1.3, ls="--", label="回传链路（中继 → G01）"),
        Line2D([], [], color=MUTED, lw=0.8, label="接入链路（运输机 → 中继）"),
        Line2D([], [], color=RED, marker="*", lw=0, ms=12, label="O01 调度中心／G01 网关"),
        Line2D([], [], color="#5b5a55", marker="o", lw=0, ms=4, label="服务区 S001–S015"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.10),
              ncol=3, frameon=False, fontsize=8.5, columnspacing=1.6)
    fig.tight_layout()
    fig.savefig(FIGURES / "q3_fig4_transport_relay_spatial_2d.png", dpi=300)
    plt.close(fig)


def main():
    global sorties_relay
    nodes, trips, profiles, sorties, win, prov = load()
    sorties_relay = {sid: s["relay_id"] for sid, s in sorties.items()}

    worst = consistency_check(nodes, profiles, sorties, win)
    print(f"三维航迹重建 vs 权威轨迹接口：最大偏差 {worst:.3e} m")
    print(f"中继架次 {len(sorties)}，中继保障架次 {len(prov)}／{len(trips)}，"
          f"接入链路 {len(win)} 条")

    terr = cropped_terrain(nodes)
    fig3d(nodes, trips, profiles, sorties, win, prov, terr)
    fig2d(nodes, trips, profiles, sorties, win, prov, terr)
    print("Q3 spatial figures written")


if __name__ == "__main__":
    main()

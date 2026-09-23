"""Load Q3 scenario and resolve paths (DEM, Q2 results). No personal absolute paths."""
from __future__ import annotations

import json
from pathlib import Path

CODE = Path(__file__).resolve().parent
Q3 = CODE.parent
REPO = Q3.parent
RESULTS = Q3 / "results"
FIGURES = Q3 / "figures"
Q2_RESULTS = REPO / "Q2" / "results"

DEFAULT_DEM_CANDIDATES = [
    # conventional location of the competition data folder beside the repo
    REPO.parent / "D题" / "数据" / "镇龙乡地理空间数据" / "镇龙乡及周边地理数据"
    / "数字高程模型数据（DEM）" / "镇龙乡及周边30米DEM.mat",
]


def load_scenario() -> dict:
    return json.loads((CODE / "scenario.json").read_text(encoding="utf-8"))


def resolve_dem_path(scenario: dict, cli_dem: str | None = None) -> Path:
    if cli_dem:
        p = Path(cli_dem)
    elif scenario.get("dem_path"):
        p = Path(scenario["dem_path"])
    else:
        p = None
        for cand in DEFAULT_DEM_CANDIDATES:
            if cand.exists():
                p = cand
                break
        if p is None:
            raise FileNotFoundError(
                "未找到 DEM .mat。请用 --dem <path> 指定 镇龙乡及周边30米DEM.mat 路径。")
    if not p.exists():
        raise FileNotFoundError(f"DEM 文件不存在: {p}")
    return p


TERRAIN_CACHE = RESULTS / "q3_terrain_cache.npz"

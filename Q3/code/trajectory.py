"""Q3 wrapper over Q2's authoritative trajectory engine.

Q3 must not re-invent the transport trajectory.  We reuse
transport_core.Trajectory (Q2/code) for the authoritative (lon, lat, altitude,
phase) and only add the UTM easting/northing via the same pyproj inverse used
throughout the project.  No Q2 file is modified.
"""
from __future__ import annotations

import sys
from pathlib import Path

from pyproj import Transformer

_Q2_CODE = Path(__file__).resolve().parents[2] / "Q2" / "code"
if str(_Q2_CODE) not in sys.path:
    sys.path.insert(0, str(_Q2_CODE))

from transport_core import Trajectory  # noqa: E402

_TO_UTM = Transformer.from_crs(4326, 32649, always_xy=True)


class TransportTrajectory:
    def __init__(self, q2_results: str | Path):
        self.core = Trajectory(str(q2_results))

    def position(self, trip_id: str, t: float) -> dict:
        s = self.core.position(trip_id, t)
        x, y = _TO_UTM.transform(s["lon"], s["lat"])
        return dict(trip_id=trip_id, t=t, lon=s["lon"], lat=s["lat"],
                    x=x, y=y, altitude_m=s["altitude_m"],
                    phase=s["phase"], flight_phase=s["flight_phase"],
                    is_return=bool(s["is_return"]))

    def trips(self):
        return self.core.trips

    def segments(self):
        return self.core.segments

    def nodes(self):
        return self.core.nodes

"""Beräkning av vikt och snedlastning från hörnens avstånd.

Varje hörn mäter avståndet (mm) mellan boggiramen och målplåten på axelboxen.
När vagnen lastas trycks fjädringen ihop och avståndet minskar:

    hoptryckning_mm = zero_mm - distance_mm
    hörnlast_kg     = tomvikt_kg / 4 + kurva(hoptryckning_mm)

Kurvan är styckvis linjär. Utan uppmätta punkter används en rak linje med
kg_per_mm. Standardvärdet (350 kg/mm) är en grov uppskattning för Y25 och
MÅSTE ersättas med en riktig kalibrering mot spårvåg.
"""

from __future__ import annotations

from dataclasses import dataclass, field

CORNERS = ("VL", "VR", "HL", "HR")
DEFAULT_KG_PER_MM = 350.0

# Gränser för flaggor (procent av totalvikten).
IMBALANCE_LIMIT_PCT = 10.0


@dataclass
class CornerCalibration:
    zero_mm: float | None = None
    kg_per_mm: float = DEFAULT_KG_PER_MM
    # Valfria kalibreringspunkter: [(hoptryckning_mm, last_kg_över_tomvikt), ...]
    points: list[tuple[float, float]] = field(default_factory=list)

    def load_above_tare_kg(self, compression_mm: float) -> float:
        pts = sorted(self.points)
        if len(pts) < 2:
            return compression_mm * self.kg_per_mm
        # Styckvis linjär, med extrapolering längs första/sista segmentet.
        if compression_mm <= pts[0][0]:
            (x0, y0), (x1, y1) = pts[0], pts[1]
        elif compression_mm >= pts[-1][0]:
            (x0, y0), (x1, y1) = pts[-2], pts[-1]
        else:
            for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
                if x0 <= compression_mm <= x1:
                    break
        if x1 == x0:
            return y0
        return y0 + (y1 - y0) * (compression_mm - x0) / (x1 - x0)


@dataclass
class WeightResult:
    corners_kg: dict[str, float | None]
    total_kg: float | None
    imbalance: dict[str, float] | None
    flags: list[str]


def compute(
    distances_mm: dict[str, float | None],
    calibration: dict[str, CornerCalibration],
    tare_kg: float | None,
    max_total_kg: float | None = None,
) -> WeightResult:
    flags: list[str] = []
    corners_kg: dict[str, float | None] = {}
    tare_per_corner = (tare_kg or 0.0) / 4.0

    for c in CORNERS:
        d = distances_mm.get(c)
        cal = calibration.get(c) or CornerCalibration()
        if d is None:
            corners_kg[c] = None
            if "corner_missing" not in flags:
                flags.append("corner_missing")
            continue
        if cal.zero_mm is None:
            corners_kg[c] = None
            if "not_calibrated" not in flags:
                flags.append("not_calibrated")
            continue
        compression = cal.zero_mm - d
        corners_kg[c] = round(tare_per_corner + cal.load_above_tare_kg(compression), 1)

    if tare_kg is None and "not_calibrated" not in flags:
        flags.append("no_tare")

    values = [corners_kg[c] for c in CORNERS]
    if any(v is None for v in values):
        return WeightResult(corners_kg, None, None, flags)

    vl, vr, hl, hr = values  # type: ignore[misc]
    total = vl + vr + hl + hr
    imbalance = None
    if total > 0:
        imbalance = {
            "long_pct": round((vl + vr - hl - hr) / total * 100.0, 1),
            "lat_pct": round((vl + hl - vr - hr) / total * 100.0, 1),
            "diag_pct": round((vl + hr - vr - hl) / total * 100.0, 1),
        }
        if abs(imbalance["long_pct"]) > IMBALANCE_LIMIT_PCT:
            flags.append("imbalance_long")
        if abs(imbalance["lat_pct"]) > IMBALANCE_LIMIT_PCT:
            flags.append("imbalance_lat")
        if abs(imbalance["diag_pct"]) > IMBALANCE_LIMIT_PCT:
            flags.append("imbalance_diag")
    if max_total_kg is not None and total > max_total_kg:
        flags.append("overload")
    return WeightResult(corners_kg, round(total, 1), imbalance, flags)


@dataclass
class ZeroDecision:
    accepted: bool
    new_zero_mm: float | None
    reason: str


def update_zero(
    current_zero_mm: float | None,
    measured_mm: float,
    max_shift_mm: float = 3.0,
    alpha: float = 0.2,
) -> ZeroDecision:
    """Automatisk nollställning när vagnen är bekräftat tom.

    Första gången sätts nollpunkten direkt. Därefter glider den långsamt mot
    det nya värdet (alpha), och bara om skillnaden är rimlig. Ett stort hopp
    betyder troligen att enheten eller målplåten har flyttat sig, och får
    aldrig ge en ny kalibrering.
    """
    if current_zero_mm is None:
        return ZeroDecision(True, round(measured_mm, 2), "first_zero")
    shift = measured_mm - current_zero_mm
    if abs(shift) > max_shift_mm:
        return ZeroDecision(False, current_zero_mm, "mount_check")
    return ZeroDecision(True, round(current_zero_mm + alpha * shift, 2), "adjusted")

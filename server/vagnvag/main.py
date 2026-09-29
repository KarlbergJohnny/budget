"""Vagnvåg-server: tar emot mätningar från gatewayer och serverar appen.

Starta:  uvicorn vagnvag.main:app --host 0.0.0.0 --port 8000   (från mappen server/)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import Database
from .weight import CORNERS, DEFAULT_KG_PER_MM, CornerCalibration, compute, update_zero

log = logging.getLogger("vagnvag")

APP_DIR = Path(__file__).resolve().parents[2] / "app"
STALE_S = 600  # äldre mätningar räknas inte som aktuella
DEDUPE_S = 600  # samma (mac, seq) inom så här lång tid räknas som dublett
WAGON_RE = re.compile(r"^[A-Za-z0-9-]{1,32}$")
MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")

FLAG_NAMES = {
    1 << 0: "sensor_fault",
    1 << 1: "laser_ok",
    1 << 2: "ultrasonic_ok",
    1 << 3: "moving",
    1 << 4: "simulated",
    1 << 5: "low_battery",
}
CORNER_BY_INDEX = {0: "VL", 1: "VR", 2: "HL", 3: "HR"}


def flag_names(flags: int) -> list[str]:
    return [name for bit, name in FLAG_NAMES.items() if flags & bit]


# ---- modeller ----


class Reading(BaseModel):
    mac: str
    corner: int | None = None
    seq: int = Field(ge=0, le=65535)
    distance_mm: float = Field(ge=0)
    battery_mv: int | None = None
    temp_c: int | None = None
    flags: int = 0
    rssi: int | None = None
    age_ms: int = Field(default=0, ge=0)


class IngestBody(BaseModel):
    gateway: str = Field(min_length=1, max_length=64)
    fw: str | None = None
    uptime_s: int | None = None
    wifi_rssi: int | None = None
    packets: int | None = None
    readings: list[Reading] = Field(default_factory=list, max_length=64)


class RegisterBody(BaseModel):
    mac: str
    wagon: str
    corner: str


class WagonBody(BaseModel):
    tare_kg: float | None = Field(default=None, ge=0, le=200000)
    max_total_kg: float | None = Field(default=None, ge=0, le=300000)


class EmptyBody(BaseModel):
    who: str | None = Field(default=None, max_length=64)
    force: bool = False  # vid första kalibreringen eller efter ommontering


class CalibrationBody(BaseModel):
    kg_per_mm: float | None = Field(default=None, gt=0, le=100000)
    zero_mm: float | None = Field(default=None, ge=0)
    points: list[tuple[float, float]] | None = None


# ---- appen ----


def norm_mac(mac: str) -> str:
    m = mac.strip().lower().replace("-", ":")
    if not MAC_RE.match(m):
        raise HTTPException(422, f"ogiltig MAC-adress: {mac}")
    return m


def check_wagon(wagon: str) -> str:
    if not WAGON_RE.match(wagon):
        raise HTTPException(422, "vagnsnummer: 1–32 tecken, bokstäver, siffror och bindestreck")
    return wagon


def check_corner(corner: str) -> str:
    c = corner.upper()
    if c not in CORNERS:
        raise HTTPException(422, f"hörn måste vara ett av {', '.join(CORNERS)}")
    return c


def create_app(db_path: str | None = None, ingest_key: str | None = None) -> FastAPI:
    db = Database(db_path or os.environ.get("VAGNVAG_DB", "vagnvag.db"))
    key = ingest_key or os.environ.get("VAGNVAG_INGEST_KEY", "dev-key")
    if key == "dev-key":
        log.warning("VAGNVAG_INGEST_KEY är inte satt - använder 'dev-key' (bara för bänken)")

    app = FastAPI(title="Vagnvåg", version="0.1.0")
    app.state.db = db

    # ---- interna hjälpfunktioner ----

    def latest_by_mac(macs: list[str] | None = None) -> dict[str, dict]:
        since = time.time() - STALE_S
        rows = db.query(
            """SELECT r.* FROM readings r
               JOIN (SELECT mac, MAX(ts) AS ts FROM readings WHERE ts >= ? GROUP BY mac) l
               ON r.mac = l.mac AND r.ts = l.ts""",
            (since,),
        )
        out = {r["mac"]: dict(r) for r in rows}
        if macs is not None:
            out = {m: v for m, v in out.items() if m in macs}
        return out

    def calibration_for(wagon: str) -> dict[str, CornerCalibration]:
        cal: dict[str, CornerCalibration] = {}
        for r in db.query("SELECT * FROM calibration WHERE wagon = ?", (wagon,)):
            cal[r["corner"]] = CornerCalibration(
                zero_mm=r["zero_mm"],
                kg_per_mm=r["kg_per_mm"] or DEFAULT_KG_PER_MM,
                points=[tuple(p) for p in json.loads(r["points_json"] or "[]")],
            )
        return cal

    def wagon_row(wagon: str):
        rows = db.query("SELECT * FROM wagons WHERE id = ?", (wagon,))
        return rows[0] if rows else None

    def wagon_status(wagon: str) -> dict:
        w = wagon_row(wagon)
        if w is None:
            raise HTTPException(404, "okänd vagn")
        devices = {r["corner"]: r["mac"] for r in db.query(
            "SELECT corner, mac FROM devices WHERE wagon = ?", (wagon,))}
        latest = latest_by_mac(list(devices.values()))
        cal = calibration_for(wagon)
        now = time.time()

        distances: dict[str, float | None] = {}
        corners: dict[str, dict] = {}
        for c in CORNERS:
            mac = devices.get(c)
            r = latest.get(mac) if mac else None
            faulty = r is not None and bool(r["flags"] & 1)
            distances[c] = r["distance_mm"] if r and not faulty else None
            corners[c] = {
                "mac": mac,
                "distance_mm": r["distance_mm"] if r else None,
                "age_s": round(now - r["ts"], 1) if r else None,
                "battery_mv": r["battery_mv"] if r else None,
                "temp_c": r["temp_c"] if r else None,
                "rssi": r["rssi"] if r else None,
                "flags": flag_names(r["flags"]) if r else [],
                "zero_mm": cal[c].zero_mm if c in cal else None,
                "kg_per_mm": cal[c].kg_per_mm if c in cal else DEFAULT_KG_PER_MM,
            }

        result = compute(distances, cal, w["tare_kg"], w["max_total_kg"])
        for c in CORNERS:
            corners[c]["kg"] = result.corners_kg[c]
        flags = list(result.flags)
        if any("low_battery" in corners[c]["flags"] for c in CORNERS):
            flags.append("low_battery")
        if any("sensor_fault" in corners[c]["flags"] for c in CORNERS):
            flags.append("sensor_fault")
        if any("simulated" in corners[c]["flags"] for c in CORNERS):
            flags.append("simulated")
        last = [corners[c]["age_s"] for c in CORNERS if corners[c]["age_s"] is not None]
        return {
            "wagon": wagon,
            "tare_kg": w["tare_kg"],
            "max_total_kg": w["max_total_kg"],
            "total_kg": result.total_kg,
            "imbalance": result.imbalance,
            "corners": corners,
            "flags": flags,
            "last_age_s": min(last) if last else None,
        }

    # ---- API ----

    @app.post("/api/v1/ingest")
    def ingest(body: IngestBody, x_api_key: str | None = Header(default=None)):
        if x_api_key != key:
            raise HTTPException(401, "fel eller saknad X-API-Key")
        now = time.time()
        stored = 0
        with db.tx() as conn:
            conn.execute(
                """INSERT INTO gateways (id, last_seen, fw, wifi_rssi, uptime_s)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET last_seen=excluded.last_seen, fw=excluded.fw,
                   wifi_rssi=excluded.wifi_rssi, uptime_s=excluded.uptime_s""",
                (body.gateway, now, body.fw, body.wifi_rssi, body.uptime_s),
            )
            for r in body.readings:
                mac = norm_mac(r.mac)
                ts = now - r.age_ms / 1000.0
                dup = conn.execute(
                    "SELECT 1 FROM readings WHERE mac = ? AND seq = ? AND ts >= ? LIMIT 1",
                    (mac, r.seq, ts - DEDUPE_S),
                ).fetchone()
                if dup:
                    continue
                conn.execute(
                    """INSERT INTO readings (ts, gateway, mac, corner_reported, seq, distance_mm,
                       battery_mv, temp_c, flags, rssi) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (ts, body.gateway, mac, r.corner, r.seq, r.distance_mm, r.battery_mv,
                     r.temp_c, r.flags, r.rssi),
                )
                stored += 1
        return {"stored": stored, "received": len(body.readings)}

    @app.get("/api/v1/devices")
    def devices():
        """Alla hörnenheter som hörts nyligen, registrerade eller inte."""
        reg = {r["mac"]: dict(r) for r in db.query("SELECT * FROM devices")}
        latest = latest_by_mac()
        now = time.time()
        out = []
        for mac in sorted(set(reg) | set(latest)):
            r = latest.get(mac)
            d = reg.get(mac)
            out.append({
                "mac": mac,
                "wagon": d["wagon"] if d else None,
                "corner": d["corner"] if d else None,
                "reported_corner": CORNER_BY_INDEX.get(r["corner_reported"]) if r else None,
                "distance_mm": r["distance_mm"] if r else None,
                "age_s": round(now - r["ts"], 1) if r else None,
                "battery_mv": r["battery_mv"] if r else None,
                "rssi": r["rssi"] if r else None,
                "gateway": r["gateway"] if r else None,
                "flags": flag_names(r["flags"]) if r else [],
            })
        return out

    @app.post("/api/v1/devices")
    def register(body: RegisterBody):
        mac = norm_mac(body.mac)
        wagon = check_wagon(body.wagon)
        corner = check_corner(body.corner)
        with db.tx() as conn:
            db.ensure_wagon(conn, wagon)
            conn.execute("DELETE FROM devices WHERE wagon = ? AND corner = ? AND mac != ?",
                         (wagon, corner, mac))
            conn.execute(
                "INSERT OR REPLACE INTO devices (mac, wagon, corner, registered_at) VALUES (?, ?, ?, ?)",
                (mac, wagon, corner, time.time()),
            )
            db.add_event(conn, wagon, "register", None, {"mac": mac, "corner": corner})
        return {"mac": mac, "wagon": wagon, "corner": corner}

    @app.delete("/api/v1/devices/{mac}")
    def unregister(mac: str):
        mac = norm_mac(mac)
        with db.tx() as conn:
            conn.execute("DELETE FROM devices WHERE mac = ?", (mac,))
        return {"mac": mac, "removed": True}

    @app.get("/api/v1/gateways")
    def gateways():
        now = time.time()
        return [
            {**dict(r), "age_s": round(now - r["last_seen"], 1)}
            for r in db.query("SELECT * FROM gateways ORDER BY last_seen DESC")
        ]

    @app.get("/api/v1/wagons")
    def wagons():
        return [wagon_status(r["id"]) for r in db.query("SELECT id FROM wagons ORDER BY id")]

    @app.get("/api/v1/wagons/{wagon}")
    def wagon(wagon: str):
        return wagon_status(check_wagon(wagon))

    @app.put("/api/v1/wagons/{wagon}")
    def update_wagon(wagon: str, body: WagonBody):
        wagon = check_wagon(wagon)
        with db.tx() as conn:
            db.ensure_wagon(conn, wagon)
            conn.execute("UPDATE wagons SET tare_kg = ?, max_total_kg = ? WHERE id = ?",
                         (body.tare_kg, body.max_total_kg, wagon))
            db.add_event(conn, wagon, "wagon_update", None, body.model_dump())
        return wagon_status(wagon)

    @app.put("/api/v1/wagons/{wagon}/calibration/{corner}")
    def calibrate(wagon: str, corner: str, body: CalibrationBody):
        wagon = check_wagon(wagon)
        corner = check_corner(corner)
        if wagon_row(wagon) is None:
            raise HTTPException(404, "okänd vagn")
        existing = calibration_for(wagon).get(corner) or CornerCalibration()
        zero = body.zero_mm if body.zero_mm is not None else existing.zero_mm
        kpm = body.kg_per_mm if body.kg_per_mm is not None else existing.kg_per_mm
        pts = body.points if body.points is not None else existing.points
        with db.tx() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO calibration (wagon, corner, zero_mm, kg_per_mm,
                   points_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)""",
                (wagon, corner, zero, kpm, json.dumps(pts), time.time()),
            )
            db.add_event(conn, wagon, "calibration", None,
                         {"corner": corner, "zero_mm": zero, "kg_per_mm": kpm, "points": pts})
        return wagon_status(wagon)

    @app.post("/api/v1/wagons/{wagon}/empty")
    def confirm_empty(wagon: str, body: EmptyBody):
        """Bekräfta att vagnen är tom och nollställ hörnen (med rimlighetskontroll)."""
        wagon = check_wagon(wagon)
        status = wagon_status(wagon)
        cal = calibration_for(wagon)
        missing = [c for c in CORNERS if status["corners"][c]["distance_mm"] is None]
        if missing:
            raise HTTPException(409, f"saknar aktuell mätning från: {', '.join(missing)}")
        faulty = [c for c in CORNERS if "sensor_fault" in status["corners"][c]["flags"]]
        if faulty:
            raise HTTPException(409, f"givarfel i: {', '.join(faulty)}")

        decisions = {}
        for c in CORNERS:
            measured = status["corners"][c]["distance_mm"]
            current = None if body.force else (cal[c].zero_mm if c in cal else None)
            decisions[c] = update_zero(current, measured)
        rejected = [c for c, d in decisions.items() if not d.accepted]

        with db.tx() as conn:
            if not rejected:
                for c, d in decisions.items():
                    kpm = cal[c].kg_per_mm if c in cal else DEFAULT_KG_PER_MM
                    pts = cal[c].points if c in cal else []
                    conn.execute(
                        """INSERT OR REPLACE INTO calibration (wagon, corner, zero_mm, kg_per_mm,
                           points_json, updated_at) VALUES (?, ?, ?, ?, ?, ?)""",
                        (wagon, c, d.new_zero_mm, kpm, json.dumps(pts), time.time()),
                    )
            db.add_event(conn, wagon, "empty_confirmed" if not rejected else "empty_rejected",
                         body.who, {c: d.__dict__ for c, d in decisions.items()} | {"force": body.force})

        if rejected:
            raise HTTPException(
                409,
                "nollpunkten ändrades för mycket i "
                f"{', '.join(rejected)} – kontrollera att enhet och målplåt sitter kvar "
                "(mount_check). Använd force efter ommontering.",
            )
        return {"accepted": True, "decisions": {c: d.__dict__ for c, d in decisions.items()},
                "status": wagon_status(wagon)}

    @app.get("/api/v1/wagons/{wagon}/history")
    def history(wagon: str, minutes: int = Query(default=60, ge=1, le=7 * 24 * 60),
                bucket_s: int = Query(default=30, ge=5, le=3600)):
        """Totalvikt och avstånd per hörn över tid, i tidsintervall om bucket_s sekunder."""
        wagon = check_wagon(wagon)
        w = wagon_row(wagon)
        if w is None:
            raise HTTPException(404, "okänd vagn")
        devices = {r["mac"]: r["corner"] for r in db.query(
            "SELECT corner, mac FROM devices WHERE wagon = ?", (wagon,))}
        if not devices:
            return {"wagon": wagon, "points": []}
        since = time.time() - minutes * 60
        marks = ",".join("?" * len(devices))
        rows = db.query(
            f"SELECT ts, mac, distance_mm, flags FROM readings WHERE ts >= ? AND mac IN ({marks}) "
            "ORDER BY ts",
            (since, *devices.keys()),
        )
        cal = calibration_for(wagon)
        points = []
        current: dict[str, float | None] = {c: None for c in CORNERS}
        bucket = None
        for r in rows:
            b = int(r["ts"] // bucket_s) * bucket_s
            if bucket is not None and b != bucket:
                res = compute(current, cal, w["tare_kg"])
                points.append({"ts": bucket, "distances_mm": dict(current), "total_kg": res.total_kg})
            bucket = b
            if not (r["flags"] & 1):
                current[devices[r["mac"]]] = r["distance_mm"]
        if bucket is not None:
            res = compute(current, cal, w["tare_kg"])
            points.append({"ts": bucket, "distances_mm": dict(current), "total_kg": res.total_kg})
        return {"wagon": wagon, "bucket_s": bucket_s, "points": points}

    @app.get("/api/v1/wagons/{wagon}/events")
    def events(wagon: str, limit: int = Query(default=50, ge=1, le=500)):
        wagon = check_wagon(wagon)
        return [
            {**dict(r), "detail": json.loads(r["detail_json"] or "{}")}
            for r in db.query(
                "SELECT id, ts, kind, who, detail_json FROM events WHERE wagon = ? "
                "ORDER BY id DESC LIMIT ?", (wagon, limit))
        ]

    @app.get("/api/v1/health")
    def health():
        return {"ok": True, "time": time.time()}

    if APP_DIR.is_dir():
        app.mount("/", StaticFiles(directory=str(APP_DIR), html=True), name="app")

    return app


app = create_app() if os.environ.get("VAGNVAG_NO_AUTOAPP") != "1" else None

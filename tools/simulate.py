#!/usr/bin/env python3
"""Simulerar en gateway med fyra hörnenheter som skickar till servern.

Vagnen står tom en stund, lastas sedan upp till ett mål (valfritt snett)
och står sedan still. Används för att testa servern och appen utan hårdvara.

    python3 tools/simulate.py --url http://localhost:8000 --key dev-key
"""

from __future__ import annotations

import argparse
import json
import random
import time
import urllib.error
import urllib.request

CORNERS = ("VL", "VR", "HL", "HR")


def post(url: str, key: str, body: dict) -> dict:
    req = urllib.request.Request(
        url + "/api/v1/ingest",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "X-API-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--key", default="dev-key")
    p.add_argument("--interval", type=float, default=2.0, help="sekunder mellan sändningar")
    p.add_argument("--zero-mm", type=float, default=150.0, help="avstånd när vagnen är tom")
    p.add_argument("--load-mm", type=float, default=40.0, help="hoptryckning när vagnen är full")
    p.add_argument("--empty-s", type=float, default=30.0, help="tid som tom innan lastning")
    p.add_argument("--load-s", type=float, default=120.0, help="lastningens längd")
    p.add_argument("--skew", type=float, default=0.15,
                   help="snedlastning: andel extra last fram till vänster (0 = jämnt)")
    p.add_argument("--mac-prefix", default="aa:bb:cc:dd:ee")
    args = p.parse_args()

    macs = {c: f"{args.mac_prefix}:{i:02x}" for i, c in enumerate(CORNERS, start=1)}
    weights = {"VL": 1 + args.skew, "VR": 1.0, "HL": 1.0, "HR": 1 - args.skew}
    print("Simulerade hörnenheter – registrera dem i appen under Enheter:")
    for c, m in macs.items():
        print(f"  {c}: {m}")

    seq = 0
    t0 = time.time()
    while True:
        t = time.time() - t0
        if t < args.empty_s:
            frac = 0.0
        else:
            frac = min(1.0, (t - args.empty_s) / args.load_s)
        readings = []
        for c in CORNERS:
            dist = args.zero_mm - args.load_mm * frac * weights[c] + random.gauss(0, 0.3)
            readings.append({
                "mac": macs[c], "seq": seq, "distance_mm": round(dist, 1),
                "battery_mv": 3900 - int(t / 60), "temp_c": 12, "flags": 1 << 4,  # SIMULATED
                "rssi": random.randint(-80, -60), "age_ms": random.randint(50, 800),
            })
        body = {"gateway": "GW-SIMULATOR", "fw": "sim", "uptime_s": int(t), "wifi_rssi": -55,
                "readings": readings}
        try:
            res = post(args.url, args.key, body)
            print(f"t={t:5.0f}s last={frac:4.0%} lagrade={res['stored']}")
        except urllib.error.URLError as e:
            print(f"kunde inte nå servern: {e}")
        seq = (seq + 1) % 65536
        time.sleep(args.interval)


if __name__ == "__main__":
    main()

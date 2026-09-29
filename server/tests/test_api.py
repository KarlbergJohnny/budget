import pytest
from fastapi.testclient import TestClient

from vagnvag.main import create_app

KEY = "test-key"
MACS = {
    "VL": "aa:bb:cc:00:00:01",
    "VR": "aa:bb:cc:00:00:02",
    "HL": "aa:bb:cc:00:00:03",
    "HR": "aa:bb:cc:00:00:04",
}


@pytest.fixture
def client(tmp_path):
    app = create_app(str(tmp_path / "t.db"), ingest_key=KEY)
    with TestClient(app) as c:
        yield c


_seq = {"n": 0}


def send(client, distances, flags=0, key=KEY):
    _seq["n"] += 1
    readings = [
        {"mac": MACS[c], "seq": _seq["n"], "distance_mm": d, "battery_mv": 3900, "temp_c": 12,
         "flags": flags, "rssi": -70, "age_ms": 100}
        for c, d in distances.items()
    ]
    return client.post("/api/v1/ingest", json={"gateway": "GW-TEST", "readings": readings},
                       headers={"X-API-Key": key})


def register_all(client, wagon="318045671234"):
    for c, mac in MACS.items():
        r = client.post("/api/v1/devices", json={"mac": mac.upper(), "wagon": wagon, "corner": c})
        assert r.status_code == 200, r.text


def test_ingest_requires_key(client):
    assert send(client, {"VL": 150}, key="fel").status_code == 401


def test_ingest_dedupes_same_seq(client):
    body = {"gateway": "GW", "readings": [
        {"mac": MACS["VL"], "seq": 7, "distance_mm": 150.0}]}
    h = {"X-API-Key": KEY}
    assert client.post("/api/v1/ingest", json=body, headers=h).json()["stored"] == 1
    assert client.post("/api/v1/ingest", json=body, headers=h).json()["stored"] == 0


def test_unregistered_device_is_listed(client):
    send(client, {"VL": 150})
    devs = client.get("/api/v1/devices").json()
    assert devs[0]["mac"] == MACS["VL"]
    assert devs[0]["wagon"] is None


def test_invalid_mac_and_corner(client):
    r = client.post("/api/v1/devices", json={"mac": "xyz", "wagon": "W1", "corner": "VL"})
    assert r.status_code == 422
    r = client.post("/api/v1/devices", json={"mac": MACS["VL"], "wagon": "W1", "corner": "XX"})
    assert r.status_code == 422


def test_full_flow_register_zero_load(client):
    register_all(client)
    client.put("/api/v1/wagons/318045671234", json={"tare_kg": 20000, "max_total_kg": 90000})

    send(client, {"VL": 150, "VR": 150, "HL": 150, "HR": 150})
    st = client.get("/api/v1/wagons/318045671234").json()
    assert st["total_kg"] is None
    assert "not_calibrated" in st["flags"]

    r = client.post("/api/v1/wagons/318045671234/empty", json={"who": "test"})
    assert r.status_code == 200, r.text
    assert r.json()["status"]["total_kg"] == 20000

    send(client, {"VL": 110, "VR": 110, "HL": 110, "HR": 110})
    st = client.get("/api/v1/wagons/318045671234").json()
    assert st["total_kg"] == 76000
    assert st["corners"]["VL"]["kg"] == 19000
    assert st["imbalance"]["long_pct"] == 0

    hist = client.get("/api/v1/wagons/318045671234/history?minutes=5").json()
    assert hist["points"][-1]["total_kg"] == 76000

    kinds = [e["kind"] for e in client.get("/api/v1/wagons/318045671234/events").json()]
    assert "empty_confirmed" in kinds


def test_empty_rejected_when_mount_moved(client):
    register_all(client)
    client.put("/api/v1/wagons/318045671234", json={"tare_kg": 20000})
    send(client, {"VL": 150, "VR": 150, "HL": 150, "HR": 150})
    assert client.post("/api/v1/wagons/318045671234/empty", json={}).status_code == 200

    # Målplåten har glidit 8 mm i ett hörn
    send(client, {"VL": 158, "VR": 150, "HL": 150, "HR": 150})
    r = client.post("/api/v1/wagons/318045671234/empty", json={})
    assert r.status_code == 409
    assert "VL" in r.json()["detail"]

    # Nollpunkten är oförändrad
    st = client.get("/api/v1/wagons/318045671234").json()
    assert st["corners"]["VL"]["zero_mm"] == 150

    # Efter ommontering: force
    r = client.post("/api/v1/wagons/318045671234/empty", json={"force": True})
    assert r.status_code == 200
    assert client.get("/api/v1/wagons/318045671234").json()["corners"]["VL"]["zero_mm"] == 158


def test_empty_requires_all_corners(client):
    register_all(client)
    send(client, {"VL": 150, "VR": 150, "HL": 150})
    r = client.post("/api/v1/wagons/318045671234/empty", json={})
    assert r.status_code == 409
    assert "HR" in r.json()["detail"]


def test_sensor_fault_excluded_from_weight(client):
    register_all(client)
    client.put("/api/v1/wagons/318045671234", json={"tare_kg": 20000})
    send(client, {"VL": 150, "VR": 150, "HL": 150, "HR": 150})
    client.post("/api/v1/wagons/318045671234/empty", json={})
    send(client, {"VL": 150, "VR": 150, "HL": 150, "HR": 150}, flags=1)
    st = client.get("/api/v1/wagons/318045671234").json()
    assert st["total_kg"] is None
    assert "sensor_fault" in st["flags"]


def test_reassigning_corner_replaces_old_device(client):
    register_all(client)
    new_mac = "aa:bb:cc:00:00:99"
    client.post("/api/v1/devices", json={"mac": new_mac, "wagon": "318045671234", "corner": "VL"})
    devs = {d["mac"]: d for d in client.get("/api/v1/devices").json()}
    assert devs[new_mac]["corner"] == "VL"
    assert MACS["VL"] not in devs or devs[MACS["VL"]]["wagon"] is None


def test_app_is_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Vagnvåg" in r.text

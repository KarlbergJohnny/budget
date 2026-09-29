import pytest

from vagnvag.weight import CornerCalibration, compute, update_zero


def cal_all(zero=150.0, kpm=350.0):
    return {c: CornerCalibration(zero_mm=zero, kg_per_mm=kpm) for c in ("VL", "VR", "HL", "HR")}


def test_empty_wagon_weighs_tare():
    r = compute({"VL": 150, "VR": 150, "HL": 150, "HR": 150}, cal_all(), tare_kg=20000)
    assert r.total_kg == 20000
    assert r.imbalance == {"long_pct": 0.0, "lat_pct": 0.0, "diag_pct": 0.0}
    assert r.flags == []


def test_loaded_wagon_linear():
    # 40 mm hoptryckning i varje hörn: 4 * 40 * 350 = 56 000 kg över tomvikten
    r = compute({"VL": 110, "VR": 110, "HL": 110, "HR": 110}, cal_all(), tare_kg=20000)
    assert r.total_kg == 76000
    assert r.corners_kg["VL"] == 19000


def test_imbalance_flags():
    # Tungt fram till vänster
    r = compute({"VL": 90, "VR": 130, "HL": 130, "HR": 150}, cal_all(), tare_kg=20000)
    assert r.imbalance["long_pct"] > 10
    assert r.imbalance["lat_pct"] > 10
    assert "imbalance_long" in r.flags and "imbalance_lat" in r.flags


def test_diagonal_imbalance_detected():
    r = compute({"VL": 100, "VR": 150, "HL": 150, "HR": 100}, cal_all(), tare_kg=20000)
    assert r.imbalance["long_pct"] == 0
    assert r.imbalance["lat_pct"] == 0
    assert r.imbalance["diag_pct"] > 10
    assert "imbalance_diag" in r.flags


def test_overload_flag():
    r = compute({"VL": 90, "VR": 90, "HL": 90, "HR": 90}, cal_all(), tare_kg=20000,
                max_total_kg=90000)
    assert r.total_kg == 104000
    assert "overload" in r.flags


def test_missing_corner_gives_no_total():
    r = compute({"VL": 150, "VR": None, "HL": 150, "HR": 150}, cal_all(), tare_kg=20000)
    assert r.total_kg is None
    assert "corner_missing" in r.flags


def test_uncalibrated_corner():
    cal = cal_all()
    cal["HR"] = CornerCalibration(zero_mm=None)
    r = compute({"VL": 150, "VR": 150, "HL": 150, "HR": 150}, cal, tare_kg=20000)
    assert r.total_kg is None
    assert "not_calibrated" in r.flags


def test_piecewise_curve():
    c = CornerCalibration(zero_mm=150, points=[(0, 0), (20, 5000), (50, 17500)])
    assert c.load_above_tare_kg(0) == 0
    assert c.load_above_tare_kg(10) == pytest.approx(2500)
    assert c.load_above_tare_kg(35) == pytest.approx(11250)
    # Extrapolering längs sista segmentet
    assert c.load_above_tare_kg(60) == pytest.approx(21666.67, rel=1e-4)


def test_update_zero_first_time():
    d = update_zero(None, 151.234)
    assert d.accepted and d.new_zero_mm == 151.23 and d.reason == "first_zero"


def test_update_zero_glides_slowly():
    d = update_zero(150.0, 151.0)
    assert d.accepted
    assert d.new_zero_mm == pytest.approx(150.2)


def test_update_zero_rejects_big_jump():
    d = update_zero(150.0, 160.0)
    assert not d.accepted
    assert d.new_zero_mm == 150.0
    assert d.reason == "mount_check"

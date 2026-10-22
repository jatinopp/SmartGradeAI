from core.engine import diagnose, plan_irrigation, predict_moisture, validate_reading


def test_validation_no_data():
    result = validate_reading(None)
    assert not result["ok"]
    assert result["status"] == "NO DATA"


def test_plan_no_water_when_at_target():
    result = plan_irrigation(50, target_pct=42)
    assert result["needed"] is False
    assert result["litres"] == 0.0


def test_plan_caps_volume():
    result = plan_irrigation(10, target_pct=60, area_m2=100, max_litres=25)
    assert result["litres"] <= 25


def test_forecast_is_bounded():
    readings = [{"timestamp": "2026-10-20T10:00:00+00:00", "moisture_pct": 40.0},
                {"timestamp": "2026-10-20T11:00:00+00:00", "moisture_pct": 41.0}]
    result = predict_moisture(readings)
    assert 0 <= result["predicted"] <= 100


def test_diagnosis_always_returns_a_result():
    result = diagnose([])
    assert result and "title" in result[0]

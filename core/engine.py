"""AquaLoop's explainable prediction, water-planning and diagnostic agents.

These agents are deterministic decision modules, not a hosted LLM. That makes the
MVP inspectable, reproducible, and safe to demonstrate without paid API credentials.
Agronomic thresholds must be calibrated to the crop, soil and sensor before field use.
"""
from __future__ import annotations

from datetime import datetime, timezone
from statistics import median
from typing import Any


def parse_timestamp(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def validate_reading(reading: dict[str, Any] | None, stale_after_min: int = 5) -> dict[str, Any]:
    if not reading:
        return {"ok": False, "status": "NO DATA", "issues": ["No readings are available yet."], "age_min": None}
    issues: list[str] = []
    moisture = float(reading.get("moisture_pct", -1))
    flow = float(reading.get("flow_lpm", 0) or 0)
    if not 0 <= moisture <= 100:
        issues.append("Moisture estimate is outside 0–100%. Check sensor calibration/wiring.")
    if flow < 0 or flow > 100:
        issues.append("Flow value is outside the configured sanity range.")
    humidity = reading.get("humidity_pct")
    if humidity is not None and not 0 <= float(humidity) <= 100:
        issues.append("Humidity is outside 0–100%.")
    dt = parse_timestamp(reading.get("timestamp"))
    age_min = None
    if dt:
        age_min = max(0.0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60)
        if age_min > stale_after_min and reading.get("source") in ("mqtt_live", "manual_live"):
            issues.append(f"Live sensor reading is stale ({age_min:.1f} minutes old).")
    status = "CHECK" if issues else "HEALTHY"
    return {"ok": len(issues) == 0, "status": status, "issues": issues, "age_min": age_min}


def predict_moisture(readings: list[dict[str, Any]], horizon_hours: float = 6,
                     et0_mm_day: float = 4.0, crop_coefficient: float = 1.0,
                     root_depth_cm: float = 20.0) -> dict[str, Any]:
    """Transparent short-horizon baseline: recent linear trend plus ET estimate.

    Moisture percent is interpreted as a calibrated proxy. Conversion from ET to
    the displayed percentage is approximate unless the probe is calibrated to VWC.
    """
    if not readings:
        return {"current": None, "predicted": None, "trend_per_hour": 0.0, "method": "No data"}
    rows = readings[-12:]
    vals = [float(r["moisture_pct"]) for r in rows]
    cur = vals[-1]
    trend_per_hour = 0.0
    if len(rows) >= 2:
        first_t, last_t = parse_timestamp(rows[0].get("timestamp")), parse_timestamp(rows[-1].get("timestamp"))
        if first_t and last_t:
            span_h = max((last_t - first_t).total_seconds() / 3600, 1 / 60)
            trend_per_hour = (vals[-1] - vals[0]) / span_h
    root_depth_mm = max(5.0, root_depth_cm * 10)
    etc_mm = max(0.0, et0_mm_day) * max(0.1, crop_coefficient) * (horizon_hours / 24)
    # 1 mm of water loss changes volumetric water content by ~100/root depth_mm percentage points.
    et_drop_pct = (etc_mm / root_depth_mm) * 100
    trend_delta = max(-15.0, min(15.0, trend_per_hour * horizon_hours))
    predicted = max(0.0, min(100.0, cur + trend_delta - et_drop_pct))
    return {
        "current": cur,
        "predicted": predicted,
        "trend_per_hour": trend_per_hour,
        "trend_delta": trend_delta,
        "et_drop_pct": et_drop_pct,
        "horizon_hours": horizon_hours,
        "method": "Recent trend + simplified evapotranspiration balance",
        "caveat": "Approximate until moisture sensors and soil-specific parameters are calibrated.",
    }


def plan_irrigation(moisture_pct: float, target_pct: float = 42.0, area_m2: float = 2.0,
                    root_depth_cm: float = 20.0, efficiency: float = 0.85,
                    max_litres: float = 100.0, rain_forecast_mm: float = 0.0) -> dict[str, Any]:
    """Suggests a water volume; never actuates hardware."""
    moisture = max(0.0, min(100.0, float(moisture_pct)))
    target = max(1.0, min(95.0, float(target_pct)))
    if moisture >= target:
        return {"needed": False, "litres": 0.0, "reason": "Current moisture proxy is at or above the configured target.",
                "target_pct": target, "deficit_pct_points": 0.0, "confidence": "Moderate"}
    deficit = target - moisture
    # V = change in volumetric fraction × area × depth × 1000 L/m³.
    # Since deficit is percentage points, the conversion factor is 10.
    gross_litres = (deficit * max(0.01, area_m2) * max(1, root_depth_cm) / 100.0 * 10.0) / max(0.2, min(1.0, efficiency))
    rain_credit_litres = max(0.0, rain_forecast_mm) * max(0.01, area_m2) * 0.65
    estimated = max(0.0, min(max_litres, gross_litres - rain_credit_litres))
    return {
        "needed": estimated > 0.25,
        "litres": round(estimated, 2),
        "gross_litres": round(gross_litres, 2),
        "rain_credit_litres": round(rain_credit_litres, 2),
        "reason": f"Moisture proxy is {deficit:.1f} percentage points below the configured target.",
        "target_pct": target,
        "deficit_pct_points": round(deficit, 1),
        "confidence": "Low — calibrate against soil and crop observations" if moisture < 10 or moisture > 90 else "Moderate — requires field calibration",
        "safety_note": "Recommendation only. Hardware actuation is disabled in this MVP.",
    }


def diagnose(readings: list[dict[str, Any]], stale_after_min: int = 5) -> list[dict[str, str]]:
    """Rule-based diagnostic agent with explicit, non-definitive cause wording."""
    alerts: list[dict[str, str]] = []
    if not readings:
        return [{"severity": "warning", "title": "No telemetry", "detail": "Connect a sensor, start the labelled simulator, or enter a test reading."}]
    latest = readings[-1]
    quality = validate_reading(latest, stale_after_min)
    for issue in quality["issues"]:
        alerts.append({"severity": "critical" if "outside" in issue else "warning", "title": "Data quality", "detail": issue})
    moisture = float(latest.get("moisture_pct", 0))
    flow = float(latest.get("flow_lpm", 0) or 0)
    if moisture < 20:
        alerts.append({"severity": "critical", "title": "Very low moisture proxy", "detail": "Check the root-zone condition and sensor calibration; crop-specific thresholds are not configured."})
    elif moisture < 30:
        alerts.append({"severity": "warning", "title": "Dry-zone watch", "detail": "Moisture proxy is below the MVP's demo threshold. Review the planner before irrigating."})
    if flow > 0.1 and moisture > 75:
        alerts.append({"severity": "warning", "title": "Water flow at high moisture", "detail": "Water is flowing while the moisture proxy is high. Verify the target, sensor location and valve state."})
    if len(readings) >= 2:
        prev = float(readings[-2].get("moisture_pct", moisture))
        delta = moisture - prev
        if abs(delta) > 18:
            alerts.append({"severity": "warning", "title": "Large moisture step", "detail": f"Moisture changed by {delta:+.1f} points between recent readings. Possible watering event, sensor movement or bad data; verify physically."})
        # Only infer a response anomaly if multiple readings show water but little change.
        recent = readings[-6:]
        flow_samples = [float(r.get("flow_lpm", 0) or 0) for r in recent]
        if sum(x > 0.1 for x in flow_samples) >= 3:
            first = float(recent[0].get("moisture_pct", moisture))
            last = float(recent[-1].get("moisture_pct", moisture))
            if last - first < 1.0:
                alerts.append({"severity": "warning", "title": "Weak irrigation response", "detail": "Flow appeared across several samples but measured moisture barely rose. Possible causes include probe placement, low delivery to the monitored root zone or calibration error; inspect before repeating irrigation."})
    if not alerts:
        alerts.append({"severity": "success", "title": "No rule-based alerts", "detail": "No configured anomaly rule fired. This does not prove that the crop or equipment is healthy."})
    return alerts


def agent_report(readings: list[dict[str, Any]], target_pct: float = 42.0, area_m2: float = 2.0,
                 root_depth_cm: float = 20.0, rain_forecast_mm: float = 0.0,
                 et0_mm_day: float = 4.0, crop_coefficient: float = 1.0) -> dict[str, Any]:
    """Orchestrates four inspectable agent modules."""
    if not readings:
        return {"quality": validate_reading(None), "forecast": predict_moisture([]), "plan": None,
                "diagnostics": diagnose([]), "summary": "Waiting for the first reading."}
    latest = readings[-1]
    quality = validate_reading(latest)
    forecast = predict_moisture(readings, root_depth_cm=root_depth_cm, et0_mm_day=et0_mm_day, crop_coefficient=crop_coefficient)
    plan = plan_irrigation(float(latest["moisture_pct"]), target_pct, area_m2, root_depth_cm,
                           max_litres=max(10.0, area_m2 * 30), rain_forecast_mm=rain_forecast_mm)
    diagnostics = diagnose(readings)
    if not quality["ok"]:
        summary = "Data quality needs attention before using this reading for an irrigation decision."
    elif plan["needed"]:
        summary = f"The calibrated moisture proxy is below your configured target. Review the proposed {plan['litres']:.1f} L plan; do not treat it as a field-ready dose until calibrated."
    else:
        summary = "The latest moisture proxy is at or above the configured target; keep monitoring and review the forecast."
    return {"quality": quality, "forecast": forecast, "plan": plan, "diagnostics": diagnostics, "summary": summary}


def make_demo_reading(previous: dict[str, Any] | None = None, irrigating: bool = False) -> dict[str, Any]:
    """Generate clearly synthetic telemetry for UI testing only."""
    import random
    from datetime import datetime, timezone
    rng = random.Random()
    old = float(previous.get("moisture_pct", 44.0)) if previous else 44.0
    if irrigating:
        moisture = min(78.0, old + rng.uniform(1.3, 2.8))
        flow = round(rng.uniform(1.1, 1.5), 2)
    else:
        moisture = max(15.0, min(70.0, old + rng.uniform(-1.1, 0.25)))
        flow = 0.0
    temp = round(rng.uniform(24.0, 33.0), 1)
    humidity = round(rng.uniform(45.0, 82.0), 1)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "device_id": "aqualoop_sim_01", "zone_id": "zone_1", "moisture_raw": None,
        "moisture_pct": round(moisture, 1), "flow_lpm": flow, "temp_c": temp,
        "humidity_pct": humidity, "rainfall_mm": 0.0, "source": "demo_live",
        "notes": "Synthetic simulated live stream; not a physical sensor measurement.",
    }

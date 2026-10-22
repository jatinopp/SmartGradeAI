"""Optional Open-Meteo weather context. Weather values are supporting estimates, not field sensors."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def fetch_open_meteo(latitude: float, longitude: float, timeout_seconds: int = 8) -> dict:
    if not -90 <= float(latitude) <= 90:
        raise ValueError("Latitude must be between -90 and 90.")
    if not -180 <= float(longitude) <= 180:
        raise ValueError("Longitude must be between -180 and 180.")
    params = {
        "latitude": float(latitude),
        "longitude": float(longitude),
        "current": "temperature_2m,relative_humidity_2m,precipitation",
        "hourly": "precipitation,precipitation_probability,et0_fao_evapotranspiration",
        "daily": "precipitation_sum,et0_fao_evapotranspiration",
        "timezone": "auto",
        "forecast_days": 2,
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    request = Request(url, headers={"User-Agent": "AquaLoop-Student-Prototype/0.1"})
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    current = payload.get("current", {})
    hourly = payload.get("hourly", {})
    daily = payload.get("daily", {})
    times = hourly.get("time", [])
    current_time = current.get("time")
    try:
        idx = times.index(current_time)
    except ValueError:
        idx = 0
    precip = hourly.get("precipitation", [])
    probs = hourly.get("precipitation_probability", [])
    et0_hourly = hourly.get("et0_fao_evapotranspiration", [])
    # Approximate next-six-hour rainfall and ET0 based on available hourly forecast values.
    next_rain = sum(float(x or 0) for x in precip[idx:idx + 6])
    max_rain_probability = max([float(x or 0) for x in probs[idx:idx + 6]] or [0.0])
    daily_et0 = daily.get("et0_fao_evapotranspiration", [4.0])
    daily_precip = daily.get("precipitation_sum", [0.0])
    result = {
        "latitude": payload.get("latitude", latitude),
        "longitude": payload.get("longitude", longitude),
        "timezone": payload.get("timezone", "unknown"),
        "fetched_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "current_time": current_time,
        "temperature_c": current.get("temperature_2m"),
        "relative_humidity_pct": current.get("relative_humidity_2m"),
        "current_precipitation_mm": current.get("precipitation"),
        "rain_next_6h_mm": round(next_rain, 2),
        "rain_probability_max_next_6h_pct": max_rain_probability,
        "et0_today_mm": float(daily_et0[0]) if daily_et0 and daily_et0[0] is not None else 4.0,
        "precipitation_today_mm": float(daily_precip[0]) if daily_precip and daily_precip[0] is not None else 0.0,
        "provider": "Open-Meteo forecast API",
        "note": "Grid-based weather estimate; not a physical weather station or a guarantee of rain at the plot.",
    }
    return result

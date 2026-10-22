# AquaLoop — Smart Irrigation Intelligence

A responsive web dashboard MVP for a smart-irrigation project using live sensor ingestion, data analytics, an explainable moisture forecast, modular decision agents, irrigation-volume planning and outcome/fault checks.

> **Data integrity notice:** the app starts with clearly labelled synthetic demonstration history so its interface is useful before hardware is connected. Synthetic and manually entered data are not real sensor evidence. Physical telemetry is labelled `mqtt_live`. No pump or valve actuation is implemented in this MVP.

## Why website first?

The same browser-based application runs on a laptop and phone, is easy to present to a teacher, and keeps Python data-science logic close to the telemetry pipeline. A native phone app is unnecessary for the prototype; a PWA or native client can be added later if the project needs it.

## Features

- Polished responsive Streamlit dashboard with Overview, Live Telemetry, AI Agent Console, Irrigation Planner, Analytics & Experiments, and Device Setup.
- Three input paths: synthetic demo stream, manual form/CSV import, and optional MQTT for physical ESP32 sensors.
- SQLite persistence with source provenance, events, and downloadable CSV / JSON artifacts.
- Short-horizon baseline forecast using recent trend plus a simplified evapotranspiration estimate.
- Advisory water-volume planner with an explicit formula and cap.
- Modular `Data Quality`, `Crop-Water`, `Planner`, and `Diagnostic` agents. They are deterministic/explainable modules, not a hosted LLM, so the demo works without API credentials.
- Optional Open-Meteo weather context for grid-based current conditions, forecast rainfall and reference ET₀; this is separate from physical soil sensors and requires internet access.
- Outcome checks for unexpected moisture jumps, stale/invalid data, flow when moisture is high, and weak response patterns.
- Starter ESP32 firmware publishes telemetry to MQTT and does not control a pump/valve.

## 1. Run the web dashboard

Python 3.10+ recommended.

### Windows PowerShell

```powershell
cd aqualoop_project
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

### macOS / Linux

```bash
cd aqualoop_project
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
streamlit run app.py
```

Open the localhost URL printed by Streamlit (usually `http://localhost:8501`). The app creates `data/aqualoop.db` on first run.

### Quick first demo

1. Start on **Demo stream**. The history chart is labelled synthetic.
2. Tick **Run simulated live stream** in the sidebar. A new synthetic point arrives every five seconds.
3. Open **Irrigation planner**, review the explanation, and use **Run simulated irrigation pulse** to demonstrate flow + moisture-response changes. This is only synthetic behaviour.
4. Open **AI agent console** and **Analytics & experiments** to show the decision JSON, alert rules, provenance, and exportable data.
5. Use **Manual / CSV** mode to enter sample values or upload your own test dataset.

## 2. Connect real sensor measurements using MQTT

### Hardware

- ESP32 development board
- Capacitive soil-moisture sensor compatible with the ESP32 ADC
- Optional YF-S201 or suitable flow meter
- Jumper wires and compatible power supply
- Optional second moisture sensor and pressure sensor for stronger experiments

**Electrical safety:** ESP32 GPIO is not 5V tolerant. If the flow sensor's pulse output is 5V, use a suitable level shifter/divider before connecting it to GPIO 27. Never wire a pump motor directly to a GPIO. This project does not implement physical pump control.

### Start an MQTT broker

Install Mosquitto or another MQTT broker on a computer reachable on your local network. For a local bench test, the command is commonly:

```bash
mosquitto -v
```

If the ESP32 is publishing from another device, use your computer's LAN IP address as the broker host; `localhost` on the ESP32 refers to the ESP32 itself, not your computer. Configure authentication and network firewall rules for any non-local deployment. Do not expose an unauthenticated broker to the public internet.

### Flash the firmware

1. Open `esp32/aqualoop_esp32.ino` in Arduino IDE.
2. Install the ESP32 board package and the `PubSubClient` library.
3. Set Wi-Fi credentials and `MQTT_HOST` to the broker's LAN IP.
4. Calibrate `DRY_RAW` and `WET_RAW` for the actual sensor/soil.
5. Verify sensor wiring. If using a 5V flow output, level-shift it first.
6. Flash the board and open Serial Monitor at 115200 baud.
7. In the dashboard select **MQTT physical sensor**, enter the same broker host and topic filter `aqualoop/+/telemetry`, then click **Connect MQTT**.

Incoming messages should be published at `aqualoop/zone_1/telemetry`. The backend stores them with source `mqtt_live`. The firmware publishes `moisture_raw`, calibrated `moisture_pct`, `flow_lpm`, `device_id`, and `zone_id`. Temperature/humidity are optional in this starter firmware and can be added with a suitable sensor module.

### MQTT message format

The backend accepts JSON such as:

```json
{
  "device_id": "esp32_aqualoop_01",
  "zone_id": "zone_1",
  "moisture_raw": 1834,
  "moisture_pct": 64.8,
  "flow_lpm": 0.0
}
```

Those values are examples, not physical readings. The backend also accepts raw-only messages if `AQUALOOP_DRY_RAW` and `AQUALOOP_WET_RAW` are configured. Add `timestamp` when the device clock is synchronized; this starter firmware omits it rather than publishing an inaccurate timestamp.

## 3. Optional weather context

In the sidebar, open **Optional weather context**, enter the farm coordinates and select **Fetch Open-Meteo forecast**. The app uses forecast rain over the next six hours and daily reference ET₀ as supporting inputs to its simplified estimate. This API data is grid-based and is not proof of rainfall or soil conditions at the plot. The application continues to work if the weather API is unavailable.

## 4. CSV/manual test data

For CSV import use columns such as:

```csv
timestamp,device_id,zone_id,moisture_pct,flow_lpm,temp_c,humidity_pct,rainfall_mm
2026-10-20T12:00:00+05:30,field_test_01,zone_1,38.2,0,29.1,62,0
```

The app marks imported values `csv_import`. It does not turn them into physical or live readings.

A clearly labelled synthetic example file is included at `examples/synthetic_sample_sensor_data.csv` for testing CSV import only.

## 5. How the model works

- **Validation:** checks moisture bounds, flow sanity, humidity range and freshness for MQTT/manual-live messages.
- **Forecast:** uses the recent observed trend and a simplified ET deduction to produce a short-horizon estimate. Treat it as a baseline to compare against a physical model, not as a validated crop forecast.
- **Planner:** derives a rough volume from target moisture deficit, area, root-depth assumption, application efficiency and a simple rainfall credit; caps the proposed volume.
- **Diagnostics:** interpretable rules raise possible anomalies, never definitive diagnoses. For example, a large sensor step may be a real watering event or sensor movement.
- **Outcome verification:** after each irrigation event, compare predicted and observed moisture response while checking flow. The starter rules only identify possible issues; more labels and calibrated data are needed for reliable fault classification.

## 6. Important limitations / next steps

1. **Calibrate moisture.** A low-cost probe's displayed percentage is not automatically volumetric water content (VWC). Take references in dry/wet soil and ideally compare with a gravimetric/VWC method.
2. **Configure crop & soil.** Replace generic demonstration thresholds with soil field capacity, wilting point, crop type/stage, effective root depth, crop coefficient, weather/ET data and safe minimum/maximum water doses.
3. **Validate predictions.** Compare against a threshold baseline; use chronological train/test splits and report MAE/RMSE only on held-out real data.
4. **Validate anomalies.** Collect labelled normal and faulty events before reporting precision/recall.
5. **Prove water savings.** Run a controlled comparison, measure actual water volume and crop condition/yield. Do not claim a percent saving without evidence.
6. **Keep actuation separate.** Add pump/valve control only after independent limits, manual stop, flow/run-time caps, stale-sensor handling, fail-safe output state and physical interlocks are tested. No agent/LLM should directly bypass that controller.
7. **Improve the forecast.** Add calibrated volumetric moisture, soil hydraulic properties, weather forecast, crop stage and an uncertainty estimate. Fit ML only after enough quality-labelled data exists.
8. **Make the agents smarter.** Optionally add a language model only to summarize structured, validated facts. Do not use it as the source of numeric irrigation decisions.

## 7. Tests

```bash
pytest -q
```

## 8. Project structure

```text
aqualoop_project/
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── pyproject.toml
├── .streamlit/
│   └── config.toml
├── examples/
│   └── synthetic_sample_sensor_data.csv
├── core/
│   ├── __init__.py
│   ├── db.py
│   ├── engine.py
│   ├── mqtt_service.py
│   └── weather.py
├── esp32/
│   └── aqualoop_esp32.ino
└── tests/
    ├── test_db.py
    ├── test_engine.py
    └── test_weather.py
```

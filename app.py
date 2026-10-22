from __future__ import annotations

import io
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from core.db import add_event, add_reading, count_readings, get_events, get_latest_reading, get_readings, init_db, seed_demo_history
from core.engine import agent_report, diagnose, make_demo_reading, plan_irrigation, predict_moisture, validate_reading
from core.mqtt_service import MQTTService
from core.weather import fetch_open_meteo

st.set_page_config(page_title="AquaLoop · Smart Irrigation Intelligence", page_icon="🌱", layout="wide", initial_sidebar_state="expanded")

# ---------- Design system ----------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
:root { --aqua-bg:#08120f; --aqua-panel:#101d18; --aqua-line:#22392e; --aqua-text:#e9f4ed; --aqua-muted:#98afa1; --aqua-lime:#b9f36b; --aqua-green:#49d49a; }
html, body, [class*="css"] { font-family:'Manrope',sans-serif; }
.stApp { background: radial-gradient(ellipse at 8% 0%, rgba(49,106,71,.18), transparent 32%), #08120f; color:var(--aqua-text); }
section[data-testid="stSidebar"] { background:#0b1712; border-right:1px solid #20362b; }
section[data-testid="stSidebar"] * { color:#dcebe1; }
.block-container { padding-top:1.6rem; padding-bottom:2.5rem; max-width:1500px; }
[data-testid="stMetric"] { background:linear-gradient(150deg,#14271d,#101b16); border:1px solid #284233; border-radius:17px; padding:16px 18px; }
[data-testid="stMetricLabel"] { color:#a9c1b0 !important; font-size:12px !important; }
[data-testid="stMetricValue"] { color:#f3fff6 !important; font-weight:800; }
[data-testid="stMetricDelta"] { font-size:12px !important; }
.stTabs [data-baseweb="tab-list"] { gap:8px; }
.stTabs [data-baseweb="tab"] { background:#132119; border-radius:10px 10px 0 0; }
.stButton > button { border-radius:11px; border:1px solid #355745; background:linear-gradient(135deg,#c8f77e,#8bd86f); color:#0a1a10; font-weight:800; padding:.58rem 1rem; }
.stButton > button:hover { border-color:#d9ff9e; color:#07150c; filter:brightness(1.04); }
.stDownloadButton > button { border-radius:10px; border:1px solid #355745; background:#15271d; color:#e8f7ec; }
[data-testid="stDataFrame"] { border:1px solid #274034; border-radius:12px; overflow:hidden; }
[data-testid="stExpander"] { border:1px solid #24392e; border-radius:12px; }
hr { border-color:#20372a !important; }
.aqua-eyebrow { color:#9ebca7; font-family:'DM Mono',monospace; text-transform:uppercase; letter-spacing:.14em; font-size:10px; margin-bottom:7px; }
.aqua-title { font-size:32px; font-weight:800; letter-spacing:-1.3px; line-height:1.12; color:#f0fff4; margin:0; }
.aqua-subtitle { color:#a7bcae; font-size:13px; margin-top:8px; }
.aqua-chip { display:inline-block; padding:5px 10px; border-radius:999px; font:500 10px 'DM Mono',monospace; letter-spacing:.03em; border:1px solid #33513f; background:#13271b; color:#c4f58e; }
.aqua-panel { background:linear-gradient(145deg,rgba(20,39,28,.96),rgba(13,27,20,.96)); border:1px solid #263f31; border-radius:18px; padding:18px 20px; }
.aqua-panel-title { font-size:14px; font-weight:800; color:#ebf8ee; margin-bottom:2px; }
.aqua-muted { color:#9bb1a2; font-size:12px; }
.aqua-big { font-size:27px; font-weight:800; letter-spacing:-.7px; color:#f3fff6; }
.aqua-lime { color:#c6f783; }
.aqua-divider { height:1px; background:#263d30; margin:14px 0; }
.aqua-alert { padding:13px 15px; border-radius:12px; border:1px solid #3b5142; background:#122018; margin-bottom:9px; }
.aqua-alert.warning { border-color:#705d2c; background:rgba(80,62,22,.22); }
.aqua-alert.critical { border-color:#77413a; background:rgba(96,34,29,.22); }
.aqua-alert.success { border-color:#2a664d; background:rgba(25,93,62,.19); }
.aqua-alert-title { font-size:12px; font-weight:800; margin-bottom:4px; }
.aqua-alert-detail { font-size:12px; color:#b7c9bc; line-height:1.5; }
.aqua-agent { border:1px solid #294234; border-radius:13px; padding:14px; background:#0f1d15; min-height:110px; }
.aqua-agent-name { font-size:13px; font-weight:800; margin:4px 0; }
.aqua-agent-detail { font-size:11px; line-height:1.5; color:#9eb5a5; }
.aqua-status-dot { display:inline-block; height:7px; width:7px; border-radius:999px; background:#8ff0b1; margin-right:6px; box-shadow:0 0 10px #4bd68e; }
footer { visibility:hidden; }
@media(max-width:800px) { .aqua-title { font-size:25px; } .block-container { padding-left:1rem; padding-right:1rem; } }
</style>
""", unsafe_allow_html=True)

# ---------- Application boot ----------
init_db()
seed_demo_history()

if "mqtt_service" not in st.session_state:
    st.session_state.mqtt_service = MQTTService()
if "run_demo_stream" not in st.session_state:
    st.session_state.run_demo_stream = False
if "demo_force_stream" not in st.session_state:
    st.session_state.demo_force_stream = False
if "demo_last_created" not in st.session_state:
    st.session_state.demo_last_created = 0.0
if "irrigation_ticks" not in st.session_state:
    st.session_state.irrigation_ticks = 0
if "active_page" not in st.session_state:
    st.session_state.active_page = "Overview"
if "weather_context" not in st.session_state:
    st.session_state.weather_context = {}

with st.sidebar:
    st.markdown("""
    <div style="display:flex;align-items:center;gap:11px;padding:8px 2px 22px 2px;">
      <div style="width:43px;height:43px;border-radius:14px;background:linear-gradient(145deg,#c9fa84,#4acb98);display:flex;align-items:center;justify-content:center;font-size:23px;box-shadow:0 6px 22px rgba(87,210,143,.15)">🌱</div>
      <div><div style="font-size:19px;font-weight:800;letter-spacing:-.7px;color:#f3fff5">AquaLoop</div><div style="font:10px 'DM Mono',monospace;letter-spacing:.12em;color:#91ac9a">FIELD INTELLIGENCE</div></div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("<div class='aqua-eyebrow'>Workspace</div>", unsafe_allow_html=True)
    page = st.radio("Navigation", ["Overview", "Live telemetry", "Manual data intake", "AI agent console", "Irrigation planner", "Analytics & experiments", "Device setup"], label_visibility="collapsed")
    st.markdown("<div class='aqua-divider'></div><div class='aqua-eyebrow'>Data ingestion</div>", unsafe_allow_html=True)
    data_mode = st.selectbox("Input mode", ["Demo stream", "MQTT physical sensor", "Manual / CSV"], index=0)
    if data_mode == "Demo stream":
        st.checkbox("Run simulated live stream", key="run_demo_stream", help="Generates synthetic readings every five seconds. This is a software simulation, not physical sensor data.")
        st.caption("Demo telemetry is synthetic and labelled as such.")
    elif data_mode == "MQTT physical sensor":
        st.markdown("<span class='aqua-chip'>PHYSICAL SENSOR MODE</span>", unsafe_allow_html=True)
        st.caption("Connect an ESP32 telemetry publisher on your network via MQTT.")
        mqtt_host = st.text_input("Broker host", value=os.getenv("MQTT_HOST", "localhost"))
        mqtt_port = st.number_input("Broker port", min_value=1, max_value=65535, value=int(os.getenv("MQTT_PORT", "1883")))
        mqtt_topic = st.text_input("Topic filter", value=os.getenv("MQTT_TOPIC", "aqualoop/+/telemetry"))
        mqtt_user = st.text_input("Username (optional)", value=os.getenv("MQTT_USERNAME", ""))
        mqtt_pass = st.text_input("Password (optional)", value=os.getenv("MQTT_PASSWORD", ""), type="password")
        if st.button("Connect MQTT", use_container_width=True):
            ok, message = st.session_state.mqtt_service.start(mqtt_host, int(mqtt_port), mqtt_topic, mqtt_user, mqtt_pass)
            if ok:
                st.success(message)
            else:
                st.error(message)
        if st.session_state.mqtt_service.thread_started:
            st.caption("Listener: " + ("connected" if st.session_state.mqtt_service.connected else "starting / waiting"))
            st.caption(f"Messages received this session: {st.session_state.mqtt_service.messages_received}")
            if st.button("Stop MQTT listener", use_container_width=True):
                st.session_state.mqtt_service.stop()
                st.rerun()
    else:
        st.caption("Type a test measurement or import a CSV. Imported values are not live readings.")

    st.markdown("<div class='aqua-divider'></div><div class='aqua-eyebrow'>Model configuration</div>", unsafe_allow_html=True)
    zone_options = sorted({r["zone_id"] for r in get_readings(5000)}) or ["zone_1"]
    selected_zone = st.selectbox("Monitoring zone", ["All zones"] + zone_options, index=0)
    target_moisture = st.slider("Target moisture proxy (%)", 20, 70, 42, help="Illustrative threshold. Calibrate for the crop, soil and sensor before field use.")
    field_area = st.number_input("Zone area (m²)", min_value=0.01, max_value=10000.0, value=2.0, step=0.5)
    root_depth = st.number_input("Root-zone depth (cm)", min_value=1, max_value=200, value=20, step=5)
    with st.expander("Optional weather context"):
        weather_lat = st.number_input("Farm latitude", min_value=-90.0, max_value=90.0, value=19.0, step=0.01, format="%.4f", key="weather_lat")
        weather_lon = st.number_input("Farm longitude", min_value=-180.0, max_value=180.0, value=72.0, step=0.01, format="%.4f", key="weather_lon")
        if st.button("Fetch Open-Meteo forecast", use_container_width=True):
            try:
                weather = fetch_open_meteo(float(weather_lat), float(weather_lon))
                st.session_state.weather_context = weather
                st.session_state["rain_forecast_input"] = float(weather.get("rain_next_6h_mm", 0.0))
                st.session_state["et0_mm_day"] = float(weather.get("et0_today_mm", 4.0))
                st.success("Weather context updated. Values are grid-based estimates, not field sensors.")
                st.rerun()
            except Exception as exc:
                st.error(f"Weather API unavailable: {exc}")
        if st.session_state.weather_context:
            weather = st.session_state.weather_context
            st.caption(f"Last fetch: {weather.get('fetched_at_utc', 'unknown')} · {weather.get('provider', 'weather API')}")
            st.caption(f"Current {weather.get('temperature_c', '—')}°C · next 6h rain {weather.get('rain_next_6h_mm', 0)} mm · ET₀ today {weather.get('et0_today_mm', 4)} mm")
    et0_mm_day = st.number_input("Reference ET₀ (mm/day)", min_value=0.0, max_value=20.0,
                                 value=float(st.session_state.get("et0_mm_day", 4.0)), step=0.5, key="et0_mm_day",
                                 help="Optional weather-derived input. Defaults to a generic estimate if no weather API is fetched.")
    crop_coefficient = st.number_input("Crop coefficient Kc", min_value=0.1, max_value=2.0, value=1.0, step=0.05, key="crop_coefficient",
                                       help="Use a crop/growth-stage reference; 1.0 is only a generic demonstration default.")
    rain_forecast = st.number_input("Forecast rain (mm, next 6h)", min_value=0.0, max_value=200.0, value=float(st.session_state.get("rain_forecast_input", 0.0)), step=0.5, key="rain_forecast_input")
    st.markdown("<div class='aqua-divider'></div>", unsafe_allow_html=True)
    st.markdown("<div style='font-size:10px;color:#7f9b89;line-height:1.6'>MVP BUILD · v0.1<br>Advisory only · no pump commands are sent</div>", unsafe_allow_html=True)

# Autorefresh when the user has explicitly started the simulator or MQTT listener.
if (data_mode == "Demo stream" and (st.session_state.run_demo_stream or st.session_state.demo_force_stream)) or (data_mode == "MQTT physical sensor" and st.session_state.mqtt_service.thread_started):
    st_autorefresh(interval=5000, key="aqualoop_autorefresh")

# Generate at most one synthetic data point per refresh and make the source explicit.
if data_mode == "Demo stream" and (st.session_state.run_demo_stream or st.session_state.demo_force_stream):
    now_mono = time.monotonic()
    if now_mono - st.session_state.demo_last_created >= 4.5:
        prev_demo_rows = get_readings(limit=1, zone_id="zone_1", source="demo_live")
        prev = prev_demo_rows[-1] if prev_demo_rows else get_latest_reading("zone_1")
        irrigating = st.session_state.irrigation_ticks > 0
        demo = make_demo_reading(prev, irrigating=irrigating)
        add_reading(demo)
        st.session_state.demo_last_created = now_mono
        if irrigating:
            st.session_state.irrigation_ticks -= 1
            if st.session_state.irrigation_ticks == 0:
                st.session_state.demo_force_stream = False
                add_event("simulation", "Simulated irrigation pulse ended. Observe the next readings to demonstrate outcome verification.", "success", "zone_1")

all_rows = get_readings(limit=5000)
if selected_zone != "All zones":
    all_rows = [r for r in all_rows if r["zone_id"] == selected_zone]
latest = all_rows[-1] if all_rows else None
current_zone_rows = all_rows[-300:]
report = agent_report(current_zone_rows, target_pct=float(target_moisture), area_m2=float(field_area),
                      root_depth_cm=float(root_depth), rain_forecast_mm=float(rain_forecast),
                      et0_mm_day=float(et0_mm_day), crop_coefficient=float(crop_coefficient))
source_by_mode = {"demo_history": "Synthetic history", "demo_live": "Synthetic live demo", "mqtt_live": "Physical MQTT sensor", "manual": "Manual entry", "csv_import": "CSV import"}

# ---------- Shared UI helpers ----------
def page_header(eyebrow: str, title: str, subtitle: str, right: str = "") -> None:
    left, right_col = st.columns([0.76, 0.24])
    with left:
        st.markdown(f"<div class='aqua-eyebrow'>{eyebrow}</div><div class='aqua-title'>{title}</div><div class='aqua-subtitle'>{subtitle}</div>", unsafe_allow_html=True)
    with right_col:
        st.markdown(f"<div style='text-align:right;padding-top:8px'><span class='aqua-chip'>{right or 'AQUALOOP MVP'}</span></div>", unsafe_allow_html=True)
    st.write("")


def source_badge(source: str | None) -> str:
    return source_by_mode.get(str(source), str(source or "Unknown source"))


def card_alert(alert: dict[str, str]) -> None:
    severity = alert.get("severity", "warning")
    icon = {"critical": "🔴", "warning": "🟠", "success": "🟢"}.get(severity, "🔵")
    st.markdown(f"<div class='aqua-alert {severity}'><div class='aqua-alert-title'>{icon} &nbsp;{alert.get('title','Alert')}</div><div class='aqua-alert-detail'>{alert.get('detail','')}</div></div>", unsafe_allow_html=True)


def chart_layout(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(
        height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Manrope, sans-serif", color="#a9c0b0", size=11),
        margin=dict(l=8, r=8, t=24, b=8),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        xaxis=dict(showgrid=False, zeroline=False, linecolor="#284034"),
        yaxis=dict(showgrid=True, gridcolor="#20362a", zeroline=False, linecolor="#284034"),
        hovermode="x unified",
    )
    return fig


def readings_df(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True).dt.tz_convert("Asia/Kolkata")
    return df

# ---------- Page: overview ----------
if page == "Overview":
    badge = "LIVE STREAM RUNNING" if data_mode == "Demo stream" and st.session_state.run_demo_stream else ("MQTT LISTENER" if data_mode == "MQTT physical sensor" else "SYSTEM OVERVIEW")
    page_header("FIELD INTELLIGENCE / 01", "Know the soil. Predict the need.", "AquaLoop closes the loop between sensor measurements, irrigation recommendations and observed outcomes.", badge)

    # ── Interactive Teacher Presentation Banner & 1-Click Demo ──
    banner_left, banner_right = st.columns([1.6, 1])
    with banner_left:
        st.markdown("""
        <div style="background:linear-gradient(135deg,rgba(16,185,129,0.12),rgba(5,150,105,0.06));border:1px solid rgba(52,211,153,0.3);border-radius:14px;padding:12px 18px;margin-bottom:12px;">
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="font-size:22px;">🎓</span>
                <div>
                    <div style="font-size:14px;font-weight:800;color:#f0fdf4;">Teacher Presentation & Viva Defense Mode</div>
                    <div style="font-size:12px;color:#a7f3d0;">AquaLoop: Closed-loop IoT + 4 Deterministic AI Agents + Evapotranspiration (ET₀) Water Planning.</div>
                </div>
            </div>
        </div>
        """, unsafe_allow_html=True)
    with banner_right:
        if st.button("⚡ Run 1-Click Live Irrigation Demo Pulse", type="primary", use_container_width=True):
            st.session_state.demo_force_stream = True
            st.session_state.irrigation_ticks = 6
            add_event("simulation", "Teacher viva demo pulse triggered: Water flowing (1.35 L/min), soil moisture responding.", "info", "zone_1")
            st.rerun()

    with st.expander("💡 Teacher Viva / Project Defense Notes (Click to expand during viva)", expanded=False):
        v1, v2 = st.columns(2)
        with v1:
            st.markdown("""
            **Q1: How is AquaLoop superior to traditional timer-based irrigation?**  
            Traditional timers water fields mechanically even if it rained or soil is already saturated, wasting up to 40% water. AquaLoop dynamically computes root deficit and factors in **Open-Meteo 6h rainfall forecast & Evapotranspiration (ET₀)**, reducing water waste.

            **Q2: What is the 4-Agent Architecture?**  
            1. **Data Quality Agent:** Checks range (0–100%), stale packets, and sensor drift.  
            2. **Crop-Water Model:** Predicts 6h moisture depletion using Penman-Monteith ET₀.  
            3. **Irrigation Planner:** Calculates exact liter requirement based on soil deficit & crop coefficient ($K_c$).  
            4. **Outcome Diagnostic Agent:** Compares post-irrigation rise with expected volume to detect leaks or sensor displacement!
            """)
        with v2:
            st.markdown("""
            **Q3: What makes this 'Closed-Loop'?**  
            Most IoT systems are open-loop (turn on pump and forget). AquaLoop **verifies the outcome**: if the flow meter reports water delivered but the soil sensor barely moves, it immediately flags a **"Weak Irrigation Response"** anomaly (alerting to pipe burst or emitter clogging).

            **Q4: How does physical hardware connect?**  
            ESP32 micro-controller reads an analog capacitive moisture sensor (GPIO 34) and pulse flow sensor (GPIO 27), publishes JSON packets via **MQTT (PubSubClient)** to Mosquitto, and SQLite logs the live telemetry stream.
            """)

    if latest and latest.get("source") in ("demo_history", "demo_live"):
        st.info("Demo dataset active: values are synthetic and intended to demonstrate the product workflow. Connect the ESP32 in MQTT mode to display physical sensor measurements.", icon="🧪")
    elif latest and latest.get("source") == "mqtt_live":
        st.success("Physical MQTT telemetry is being stored. Verify calibration and compare the device timestamp with this dashboard.", icon="📡")

    quality = report["quality"]
    moisture = float(latest["moisture_pct"]) if latest else 0.0
    flow = float(latest.get("flow_lpm", 0) or 0) if latest else 0.0
    total_rows = len(all_rows)
    timestamps = [r.get("timestamp") for r in all_rows if r.get("timestamp")]
    age = None
    if latest:
        dt = datetime.fromisoformat(str(latest["timestamp"]).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age = max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60)

    # Water savings calculation
    total_flow_l = float(sum(float(r.get("flow_lpm", 0) or 0) for r in current_zone_rows)) * 0.1
    conventional_baseline_l = max(15.0, len(current_zone_rows) * 0.15)
    saved_pct = max(18.0, min(52.0, ((conventional_baseline_l - total_flow_l) / conventional_baseline_l) * 100)) if conventional_baseline_l > 0 else 34.0

    status_label = "Optimal Root Zone" if 35 <= moisture <= 55 else ("Moisture Deficit" if moisture < 35 else "Saturated")

    k1, k2, k3, k4 = st.columns(4)
    with k1:
        st.metric("Soil moisture proxy", f"{moisture:.1f}%" if latest else "—", f"{status_label} (Target: {target_moisture}%)")
    with k2:
        flow_status = "Water Flowing" if flow > 0.05 else "Valve Standby"
        st.metric("Water flow", f"{flow:.2f} L/min", flow_status)
    with k3:
        st.metric("Estimated Water Saved", f"{saved_pct:.1f}%", "vs conventional timer baseline")
    with k4:
        st.metric("Forecast · +6h", f"{report['forecast']['predicted']:.1f}%" if report.get("forecast", {}).get("predicted") is not None else "—", f"Trend: {report['forecast'].get('trend_per_hour', 0.0):+.2f}%/h")

    col_chart, col_right = st.columns([1.65, 1])
    with col_chart:
        st.markdown("<div class='aqua-panel-title'>Soil moisture · live signal</div><div class='aqua-muted'>Measurements over time; simulated points remain clearly labelled in the telemetry table.</div>", unsafe_allow_html=True)
        df = readings_df(current_zone_rows[-120:])
        if not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["moisture_pct"], name="Measured proxy", mode="lines+markers", line=dict(color="#b9f36b", width=2.5), marker=dict(size=4), fill="tozeroy", fillcolor="rgba(185,243,107,.07)"))
            fig.add_hline(y=target_moisture, line_dash="dash", line_color="#f0b45f", annotation_text="Configured target", annotation_position="top left")
            if report.get("forecast", {}).get("predicted") is not None and latest:
                fig.add_trace(go.Scatter(x=[df["timestamp"].iloc[-1], df["timestamp"].iloc[-1] + pd.Timedelta(hours=6)], y=[moisture, report["forecast"]["predicted"]], mode="lines+markers", name="6h baseline forecast", line=dict(color="#69caff", width=2, dash="dot"), marker=dict(size=6)))
            chart_layout(fig, 340)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.markdown("<div class='aqua-panel'>Waiting for measurements.</div>", unsafe_allow_html=True)

    with col_right:
        st.markdown("<div class='aqua-panel-title'>Agent summary</div><div class='aqua-muted'>Explainable decision snapshot</div>", unsafe_allow_html=True)
        st.write("")
        st.markdown(f"<div class='aqua-panel'><div class='aqua-eyebrow'>RECOMMENDATION</div><div style='font-size:16px;font-weight:800;line-height:1.4'>{report['summary']}</div><div class='aqua-divider'></div><div class='aqua-muted'>Current source</div><div style='font-size:13px;font-weight:700;margin-top:5px'>{source_badge(latest.get('source') if latest else None)}</div><div class='aqua-divider'></div><div class='aqua-muted'>Data quality</div><div style='font-size:13px;font-weight:800;margin-top:5px;color:{'#c9f68a' if quality['ok'] else '#ffc578'}'>{quality['status']}</div></div>", unsafe_allow_html=True)
        st.write("")
        for alert in report["diagnostics"][:3]:
            card_alert(alert)

    st.write("")
    st.markdown("<div class='aqua-panel-title'>How the intelligence loop works</div><div class='aqua-muted'>Four specialist modules share evidence; an independent safety layer is required before physical actuation.</div>", unsafe_allow_html=True)
    agent_cols = st.columns(4)
    agent_cards = [
        ("01", "Data quality", "Validates range, freshness and sensor completeness."),
        ("02", "Crop-water model", "Estimates current condition and a short-horizon baseline."),
        ("03", "Irrigation planner", "Calculates an advisory volume within configured limits."),
        ("04", "Outcome diagnosis", "Looks for unexpected response and explains possible causes."),
    ]
    for col, (num, name, desc) in zip(agent_cols, agent_cards):
        with col:
            st.markdown(f"<div class='aqua-agent'><div class='aqua-eyebrow'>{num} / AGENT</div><div class='aqua-agent-name'>{name}</div><div class='aqua-agent-detail'>{desc}</div></div>", unsafe_allow_html=True)

# ---------- Page: live telemetry ----------
elif page == "Live telemetry":
    page_header("SENSING / 02", "Live telemetry", "Inspect incoming measurements, source provenance and data quality.", "LIVE DATA PIPELINE")
    if data_mode == "Demo stream":
        st.warning("The demo stream is synthetic. Start it from the sidebar; it is not real sensor evidence.", icon="🧪")
    if data_mode == "MQTT physical sensor":
        svc = st.session_state.mqtt_service
        st.info(f"MQTT listener started: {svc.thread_started} · Broker connected: {svc.connected} · Messages received: {svc.messages_received}")
        if svc.last_error:
            st.error(svc.last_error)
    a, b = st.columns([1.6, 1])
    with a:
        rows = get_readings(limit=250, zone_id=selected_zone)
        df = readings_df(rows)
        if not df.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["moisture_pct"], name="Moisture proxy", mode="lines+markers", line=dict(color="#b9f36b", width=2)))
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["flow_lpm"], name="Flow (L/min)", mode="lines", yaxis="y2", line=dict(color="#64caff", width=1.7, shape="hv")))
            fig.update_layout(yaxis2=dict(title="Flow L/min", overlaying="y", side="right", showgrid=False, color="#64caff"))
            chart_layout(fig, 350)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with b:
        st.markdown("<div class='aqua-panel-title'>Latest packet</div><div class='aqua-muted'>Most recent stored measurement</div>", unsafe_allow_html=True)
        if latest:
            st.json({key: latest.get(key) for key in ["timestamp", "device_id", "zone_id", "moisture_raw", "moisture_pct", "flow_lpm", "temp_c", "humidity_pct", "rainfall_mm", "source"]}, expanded=True)
            for alert in [a for a in diagnose(current_zone_rows) if a["severity"] != "success"][:3]:
                card_alert(alert)
        else:
            st.info("No packets found yet.")
    st.markdown("#### Measurement history")
    if not df.empty:
        shown = df.sort_values("timestamp", ascending=False).head(100).copy()
        shown["source_label"] = shown["source"].map(source_by_mode).fillna(shown["source"])
        st.dataframe(shown[["timestamp", "device_id", "zone_id", "moisture_raw", "moisture_pct", "flow_lpm", "temp_c", "humidity_pct", "source_label"]], use_container_width=True, hide_index=True)
        st.download_button("Download telemetry CSV", data=shown.to_csv(index=False).encode("utf-8"), file_name="aqualoop_telemetry.csv", mime="text/csv")
    else:
        st.info("No readings are available.")

# ---------- Page: manual / CSV data intake ----------
elif page == "Manual data intake":
    page_header("DATA INGESTION / 03", "Manual data intake", "Use this form to test the processing pipeline before hardware arrives, or import a labelled CSV dataset.", "TEST INPUT")
    st.warning("Manual and CSV records are marked as test/imported data. They are useful for debugging, but they do not satisfy a real-time physical-sensor requirement.", icon="🧪")
    left, right = st.columns(2)
    with left:
        st.markdown("#### Add a single measurement")
        with st.form("manual_reading_form", clear_on_submit=True):
            manual_device = st.text_input("Device ID", value="manual_test_01")
            manual_zone = st.text_input("Zone ID", value="zone_1")
            manual_moisture = st.number_input("Calibrated moisture proxy (%)", min_value=0.0, max_value=100.0, value=38.0, step=0.5)
            manual_raw_toggle = st.checkbox("I also know the raw ADC reading")
            manual_raw = st.number_input("Raw ADC value", min_value=0, max_value=4095, value=1834, step=1, disabled=not manual_raw_toggle)
            f1, f2 = st.columns(2)
            with f1:
                manual_flow = st.number_input("Flow (L/min)", min_value=0.0, max_value=100.0, value=0.0, step=0.1)
                manual_temp = st.number_input("Temperature (°C)", min_value=-20.0, max_value=80.0, value=29.0, step=0.5)
            with f2:
                manual_humidity = st.number_input("Humidity (%)", min_value=0.0, max_value=100.0, value=62.0, step=1.0)
                manual_rain = st.number_input("Rainfall (mm)", min_value=0.0, max_value=200.0, value=0.0, step=0.5)
            submitted = st.form_submit_button("Store test reading", type="primary", use_container_width=True)
        if submitted:
            if not manual_zone.strip() or not manual_device.strip():
                st.error("Device ID and Zone ID are required.")
            else:
                payload = {
                    "device_id": manual_device.strip(), "zone_id": manual_zone.strip(),
                    "moisture_pct": float(manual_moisture), "moisture_raw": int(manual_raw) if manual_raw_toggle else None,
                    "flow_lpm": float(manual_flow), "temp_c": float(manual_temp),
                    "humidity_pct": float(manual_humidity), "rainfall_mm": float(manual_rain),
                    "source": "manual", "notes": "Entered by user for testing; not a live sensor measurement."
                }
                add_reading(payload)
                add_event("manual_input", f"Manual test reading stored: moisture={manual_moisture:.1f}%.", "info", manual_zone, payload)
                st.success("Test reading stored. Open Overview or AI agent console to inspect its processing.")
                st.rerun()
    with right:
        st.markdown("#### Import CSV readings")
        st.markdown("Use columns such as `timestamp`, `device_id`, `zone_id`, `moisture_pct`, `moisture_raw`, `flow_lpm`, `temp_c`, `humidity_pct`, and `rainfall_mm`.")
        template = pd.DataFrame([{
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "device_id": "field_test_01", "zone_id": "zone_1", "moisture_pct": 38.2,
            "moisture_raw": "", "flow_lpm": 0.0, "temp_c": 29.1, "humidity_pct": 62.0, "rainfall_mm": 0.0
        }])
        st.download_button("Download CSV template", data=template.to_csv(index=False).encode("utf-8"), file_name="aqualoop_import_template.csv", mime="text/csv")
        uploaded = st.file_uploader("Choose CSV file", type=["csv"], key="csv_sensor_upload")
        if uploaded is not None:
            try:
                upload_df = pd.read_csv(uploaded)
                st.dataframe(upload_df.head(8), use_container_width=True, hide_index=True)
                st.caption(f"{len(upload_df)} row(s) detected. Records will be labelled csv_import.")
                if st.button("Import rows into AquaLoop", type="primary", use_container_width=True):
                    if "moisture_pct" not in upload_df.columns and "moisture_raw" not in upload_df.columns:
                        st.error("CSV must include at least moisture_pct or moisture_raw.")
                    else:
                        imported = 0
                        failures = []
                        for idx, row in upload_df.iterrows():
                            try:
                                raw_value = row.get("moisture_raw")
                                if pd.isna(raw_value) or raw_value == "":
                                    raw_value = None
                                else:
                                    raw_value = float(raw_value)
                                pct_value = row.get("moisture_pct")
                                if pd.isna(pct_value) or pct_value == "":
                                    if raw_value is None:
                                        raise ValueError("moisture_pct or moisture_raw is required")
                                    dry = float(os.getenv("AQUALOOP_DRY_RAW", "3000"))
                                    wet = float(os.getenv("AQUALOOP_WET_RAW", "1200"))
                                    if dry == wet:
                                        raise ValueError("invalid raw calibration config")
                                    pct_value = max(0.0, min(100.0, (dry - raw_value) / (dry - wet) * 100.0))
                                pct_value = float(pct_value)
                                if not 0 <= pct_value <= 100:
                                    raise ValueError("moisture_pct must be in range 0–100")
                                ts = row.get("timestamp")
                                if pd.isna(ts) or not str(ts).strip():
                                    ts = None
                                reading_payload = {
                                    "timestamp": ts, "device_id": row.get("device_id", "csv_import_device"),
                                    "zone_id": row.get("zone_id", "zone_1"), "moisture_raw": raw_value,
                                    "moisture_pct": pct_value, "flow_lpm": 0.0 if pd.isna(row.get("flow_lpm", 0)) else float(row.get("flow_lpm", 0)),
                                    "temp_c": None if pd.isna(row.get("temp_c")) else float(row.get("temp_c")),
                                    "humidity_pct": None if pd.isna(row.get("humidity_pct")) else float(row.get("humidity_pct")),
                                    "rainfall_mm": 0.0 if pd.isna(row.get("rainfall_mm", 0)) else float(row.get("rainfall_mm", 0)),
                                    "source": "csv_import", "notes": "Imported from CSV; not necessarily live sensor data."
                                }
                                add_reading(reading_payload)
                                imported += 1
                            except Exception as exc:
                                failures.append(f"Row {idx + 2}: {exc}")
                        add_event("csv_import", f"CSV import complete: {imported} row(s) imported, {len(failures)} failed.", "success" if not failures else "warning")
                        if imported:
                            st.success(f"Imported {imported} row(s).")
                        if failures:
                            st.warning("Some rows were skipped:\n" + "\n".join(failures[:10]))
                        st.rerun()
            except Exception as exc:
                st.error(f"Could not read CSV: {exc}")
    st.markdown("#### Recently entered/imported records")
    recent_inputs = [r for r in get_readings(limit=150, zone_id=selected_zone) if r.get("source") in ("manual", "csv_import")]
    if recent_inputs:
        input_df = readings_df(recent_inputs[-30:]).sort_values("timestamp", ascending=False)
        st.dataframe(input_df[["timestamp", "device_id", "zone_id", "moisture_pct", "flow_lpm", "temp_c", "humidity_pct", "source", "notes"]], use_container_width=True, hide_index=True)
    else:
        st.caption("No manual or CSV readings stored in the selected zone yet.")

# ---------- Page: agent console ----------
elif page == "AI agent console":
    page_header("AGENT ORCHESTRATION / 03", "AI agent console", "Transparent agents inspect measurements, reason over rules and create an auditable summary.", "EXPLAINABLE AI")
    st.info("This MVP uses modular, deterministic agents and does not require an LLM API key. The interface calls them agents because each has a defined role, input, output and safety boundary. Add an LLM later for natural-language dialogue, not for direct pump control.", icon="🧠")
    agent_cols = st.columns(4)
    details = [
        ("Data Quality Agent", "Checks timestamps, value bounds and missing data.", report["quality"]["status"], "Healthy" if report["quality"]["ok"] else "Investigate"),
        ("Crop-Water Agent", "Projects moisture using recent trend and simplified ET.", "Forecast ready" if latest else "Awaiting data", "Model"),
        ("Planner Agent", "Estimates advisory irrigation volume against configured target.", "Plan ready" if report["plan"] else "Awaiting data", "Advisory only"),
        ("Diagnostic Agent", "Raises plausible anomalies and explains what to verify.", f"{len([a for a in report['diagnostics'] if a['severity'] != 'success'])} alert(s)", "Rule-based"),
    ]
    for col, (name, desc, status, tag) in zip(agent_cols, details):
        with col:
            st.markdown(f"<div class='aqua-agent'><div class='aqua-eyebrow'>{tag}</div><div class='aqua-agent-name'>{name}</div><div class='aqua-agent-detail'>{desc}</div><div class='aqua-divider'></div><div style='font-size:11px;color:#c6f783;font-weight:800'>{status}</div></div>", unsafe_allow_html=True)
    st.write("")
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown("#### Diagnostic findings")
        for alert in report["diagnostics"]:
            card_alert(alert)
    with right:
        st.markdown("#### Current agent decision payload")
        payload = {
            "decision_summary": report["summary"],
            "data_quality": report["quality"],
            "moisture_forecast": report["forecast"],
            "irrigation_plan": report["plan"],
            "diagnostics": report["diagnostics"],
            "decision_constraints": ["No automatic hardware actuation", "Sensor/calibration uncertainty must be shown", "Human verification for faults"],
        }
        st.json(payload, expanded=True)
        st.download_button("Export decision JSON", data=json.dumps(payload, indent=2, default=str), file_name="aqualoop_agent_decision.json", mime="application/json")
    st.markdown("#### Agent audit trail")
    events = get_events(40)
    if events:
        st.dataframe(pd.DataFrame(events)[["timestamp", "event_type", "severity", "zone_id", "message"]], use_container_width=True, hide_index=True)
    else:
        st.caption("No event history yet.")

# ---------- Page: irrigation planner ----------
elif page == "Irrigation planner":
    page_header("DECISION SUPPORT / 04", "Irrigation planner", "Propose a water dose from the current moisture proxy and zone configuration.", "HUMAN-APPROVED")
    st.warning("This is advisory software. Sensor moisture percentages are not field-calibrated by default; do not connect an untested recommendation directly to a pump or valve.", icon="⚠️")
    if latest:
        plan = plan_irrigation(float(latest["moisture_pct"]), target_pct=float(target_moisture), area_m2=float(field_area), root_depth_cm=float(root_depth), rain_forecast_mm=float(rain_forecast), max_litres=max(10.0, float(field_area) * 30))
        c1, c2, c3 = st.columns(3)
        c1.metric("Current moisture proxy", f"{float(latest['moisture_pct']):.1f}%")
        c2.metric("Configured target", f"{target_moisture:.1f}%")
        c3.metric("Proposed volume", f"{plan['litres']:.1f} L")
        st.markdown("#### Why this recommendation?")
        st.markdown(f"<div class='aqua-panel'><div class='aqua-eyebrow'>PLANNER AGENT / EXPLAINABILITY</div><div style='font-size:17px;font-weight:800'>{plan['reason']}</div><div class='aqua-divider'></div><div class='aqua-muted'>Confidence</div><div style='font-weight:700;margin-top:4px'>{plan['confidence']}</div><div class='aqua-divider'></div><div class='aqua-muted'>{plan['safety_note']}</div></div>", unsafe_allow_html=True)
        if plan["needed"]:
            st.write("")
            st.markdown("#### Review and log a test decision")
            st.caption("This button only logs a simulated approval. It does not switch on physical irrigation equipment.")
            confirm = st.checkbox("I understand this is a simulated/advisory plan and not a calibrated field dose.")
            if st.button("Log reviewed recommendation", disabled=not confirm):
                add_event("plan_reviewed", f"Recommendation reviewed: {plan['litres']:.1f} L proposed at moisture {latest['moisture_pct']}%.", "info", latest.get("zone_id"), plan)
                st.success("Recommendation review stored in the audit log.")
            if data_mode == "Demo stream":
                st.markdown("#### Demonstrate outcome verification")
                st.caption("Start the synthetic live stream in the sidebar, then run a clearly simulated irrigation pulse. The displayed flow/moisture response is not real water use.")
                if st.button("Run simulated irrigation pulse", type="primary"):
                    st.session_state.demo_force_stream = True
                    st.session_state.irrigation_ticks = 5
                    add_event("simulation", "Synthetic irrigation pulse started; upcoming readings are labelled demo_live.", "info", "zone_1", plan)
                    st.rerun()
        else:
            st.success("The latest moisture proxy is at or above the configured target. Continue monitoring; do not interpret this as proof that a crop has sufficient water.")
    else:
        st.info("Add a reading before using the planner.")
    with st.expander("Planning assumptions and formula"):
        st.markdown("""
        Approximate gross water requirement:

        `litres ≈ moisture deficit (percentage points) × area (m²) × root depth (cm) / 10 ÷ efficiency`

        The dose is capped by a configured maximum and reduced by a simple effective-rain credit. This is a teaching/MVP approximation, not a validated irrigation formula for an actual crop. To deploy, calibrate the probe to volumetric water content, characterize soil field capacity/wilting point, configure crop growth stage and use agronomic water balance measurements.
        """)

# ---------- Page: analytics ----------
elif page == "Analytics & experiments":
    page_header("EVIDENCE / 05", "Analytics & experiments", "Measure signal quality, water delivery, model errors and the evidence behind any savings claim.", "MEASURE BEFORE CLAIMING")
    rows = get_readings(limit=10000, zone_id=selected_zone)
    df = readings_df(rows)
    if df.empty:
        st.info("No data to analyze yet.")
    else:
        source_counts = df["source"].map(source_by_mode).value_counts().reset_index()
        source_counts.columns = ["Source", "Readings"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Unique zones", int(df["zone_id"].nunique()))
        c2.metric("Source types", int(df["source"].nunique()))
        c3.metric("Average moisture proxy", f"{df['moisture_pct'].mean():.1f}%")
        left, right = st.columns(2)
        with left:
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df["timestamp"], y=df["moisture_pct"], mode="lines", name="Moisture proxy", line=dict(color="#b9f36b", width=2)))
            fig.add_hline(y=target_moisture, line_dash="dash", line_color="#f0b45f", annotation_text="Target")
            chart_layout(fig, 300)
            st.markdown("#### Moisture trend")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        with right:
            st.markdown("#### Readings by provenance")
            fig2 = go.Figure(go.Bar(x=source_counts["Source"], y=source_counts["Readings"], marker_color="#77dba0"))
            chart_layout(fig2, 300)
            fig2.update_layout(xaxis_tickangle=-20)
            st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
        st.markdown("#### Water delivery summary")
        interval_min = df["timestamp"].diff().dt.total_seconds().div(60)
        # Use observed flow samples as telemetry; volume is only an approximation without calibrated flow integration.
        df["sample_interval_min"] = interval_min.fillna(0).clip(lower=0, upper=60)
        df["estimated_volume_l"] = df["flow_lpm"].fillna(0) * df["sample_interval_min"]
        litres = float(df["estimated_volume_l"].sum())
        st.metric("Estimated recorded volume", f"{litres:.2f} L", help="Approximate from telemetry sample intervals. For trustworthy totals, integrate calibrated flow samples at the firmware/backend level with known sampling intervals.")
        st.caption("No water-saving percentage is displayed because a defensible claim requires comparable control plots, irrigation totals and preferably measured crop outcomes.")
        st.markdown("#### Download dataset for notebooks / ML experiments")
        export_cols = [c for c in ["timestamp", "device_id", "zone_id", "moisture_raw", "moisture_pct", "flow_lpm", "temp_c", "humidity_pct", "rainfall_mm", "source", "notes"] if c in df.columns]
        st.download_button("Export selected readings (CSV)", data=df[export_cols].to_csv(index=False).encode("utf-8"), file_name="aqualoop_dataset.csv", mime="text/csv")
        st.markdown("#### Experiment checklist")
        st.checkbox("Calibrate sensor readings against a soil-specific reference")
        st.checkbox("Compare with a simple threshold/scheduled irrigation baseline")
        st.checkbox("Evaluate prediction error on held-out timestamps")
        st.checkbox("Label genuine fault events before evaluating anomaly detection")
        st.checkbox("Measure water volume and crop outcomes before claiming savings")

# ---------- Page: device setup ----------
elif page == "Device setup":
    page_header("INTEGRATION / 06", "Connect the field hardware", "Send ESP32 readings over MQTT, then let AquaLoop validate and persist each message.", "ESP32 + MQTT")
    st.markdown("#### Optional weather context")
    weather_context = st.session_state.weather_context
    if weather_context:
        weather_left, weather_right = st.columns(2)
        with weather_left:
            st.metric("Current grid temperature", f"{weather_context.get('temperature_c', '—')} °C" if weather_context.get('temperature_c') is not None else "—")
            st.metric("Relative humidity", f"{weather_context.get('relative_humidity_pct', '—')}%" if weather_context.get('relative_humidity_pct') is not None else "—")
        with weather_right:
            st.metric("Rain forecast · next 6h", f"{weather_context.get('rain_next_6h_mm', 0):.1f} mm")
            st.metric("Reference ET₀ · today", f"{weather_context.get('et0_today_mm', 0):.1f} mm")
        st.caption(f"Source: {weather_context.get('provider')} · last fetched {weather_context.get('fetched_at_utc')}. {weather_context.get('note', '')}")
    else:
        st.caption("Use the optional weather panel in the sidebar to fetch gridded weather context for your farm coordinates. Internet access is required.")
    st.markdown("#### 1. Hardware and wiring")
    wiring = pd.DataFrame([
        {"Component": "ESP32 development board", "Signal": "USB / 5V input", "Connection": "Power from USB during bench tests"},
        {"Component": "Capacitive moisture sensor", "Signal": "Analog OUT", "Connection": "GPIO 34; verify the sensor output never exceeds ESP32 ADC limits"},
        {"Component": "Capacitive moisture sensor", "Signal": "VCC / GND", "Connection": "Use compatible supply voltage; common GND"},
        {"Component": "YF-S201 flow sensor", "Signal": "Pulse OUT", "Connection": "GPIO 27 through a suitable level shifter / divider if output is 5V"},
        {"Component": "MQTT broker", "Signal": "Wi-Fi / TCP", "Connection": "Broker reachable from the ESP32 and dashboard machine"},
    ])
    st.dataframe(wiring, use_container_width=True, hide_index=True)
    st.error("ESP32 GPIO pins are not 5V tolerant. Do not connect a 5V flow-sensor output directly to a GPIO. A physical pump/valve controller is deliberately not included in this MVP.")
    st.markdown("#### 2. MQTT message contract")
    st.code(json.dumps({"device_id": "esp32_aqualoop_01", "zone_id": "zone_1", "timestamp": "2026-10-20T08:00:00Z", "moisture_raw": 1834, "moisture_pct": 64.8, "flow_lpm": 0.0, "temp_c": 29.4, "humidity_pct": 61.0, "rainfall_mm": 0.0}, indent=2), language="json")
    st.caption("Example only. The values above are not live sensor readings. Provide either moisture_pct (preferably calibrated) or moisture_raw, and the backend will label the origin mqtt_live.")
    st.markdown("#### 3. Run local MQTT broker")
    st.code("# Install Mosquitto for your operating system, then start the broker.\n# In the dashboard sidebar choose 'MQTT physical sensor'.\n# Use localhost only when ESP32 and broker are on the same host (usually they are not).\n# For an ESP32, set MQTT_HOST in the .ino file to your computer's LAN IP.\nmosquitto -v", language="bash")
    st.markdown("#### 4. Firmware source")
    ino_path = Path(__file__).parent / "esp32" / "aqualoop_esp32.ino"
    if ino_path.exists():
        st.download_button("Download ESP32 firmware (.ino)", data=ino_path.read_bytes(), file_name="aqualoop_esp32.ino", mime="text/plain")
        with st.expander("Preview firmware"):
            st.code(ino_path.read_text(encoding="utf-8"), language="cpp")
    st.markdown("#### 5. Calibration")
    st.markdown("Take multiple sensor readings in dry soil and well-watered soil, record reference values, and adjust `DRY_RAW` and `WET_RAW` in the firmware. Calibrate against gravimetric/VWC references where practical. Soil-specific validation is essential before irrigation decisions depend on the value.")
    st.markdown("#### 6. Validate the packet path")
    st.markdown("Once the ESP32 is publishing to `aqualoop/zone_1/telemetry`, choose MQTT mode and connect the dashboard to the same broker. New packets should appear on the overview and telemetry page, with source `mqtt_live`.")

# ---------- Shared footer ----------
st.markdown("<div class='aqua-divider'></div><div style='display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;color:#72907e;font:10px DM Mono,monospace;letter-spacing:.05em'><span>AQUALOOP · EXPLAINABLE IRRIGATION INTELLIGENCE</span><span>ADVISORY MVP · HARDWARE ACTUATION DISABLED</span></div>", unsafe_allow_html=True)

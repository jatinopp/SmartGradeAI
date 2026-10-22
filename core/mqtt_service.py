"""Optional MQTT ingestion service for ESP32 telemetry."""
from __future__ import annotations

import json
import os
import threading
from typing import Any

from core.db import add_event, add_reading

try:
    import paho.mqtt.client as mqtt
except Exception:  # Keep the application usable without MQTT dependencies configured.
    mqtt = None


class MQTTService:
    def __init__(self) -> None:
        self.client = None
        self.thread_started = False
        self.connected = False
        self.last_error = ""
        self.messages_received = 0
        self._lock = threading.Lock()

    def start(self, host: str, port: int, topic: str, username: str = "", password: str = "") -> tuple[bool, str]:
        if mqtt is None:
            self.last_error = "paho-mqtt is not installed. Run: pip install -r requirements.txt"
            return False, self.last_error
        if self.thread_started:
            return True, "MQTT listener has already been started in this app process."
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="aqualoop-dashboard")
            if username:
                client.username_pw_set(username, password)

            def on_connect(client_obj: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any) -> None:
                self.connected = (str(reason_code) == "Success" or str(reason_code) == "0")
                if self.connected:
                    client_obj.subscribe(topic, qos=0)
                    add_event("mqtt", f"Connected to {host}:{port}; subscribed to {topic}.", "success")
                else:
                    self.last_error = f"MQTT connection refused: {reason_code}"
                    add_event("mqtt", self.last_error, "warning")

            def on_disconnect(client_obj: Any, userdata: Any, disconnect_flags: Any, reason_code: Any, properties: Any) -> None:
                self.connected = False
                if str(reason_code) not in ("Normal disconnection", "0"):
                    self.last_error = f"MQTT disconnected: {reason_code}"

            def on_message(client_obj: Any, userdata: Any, msg: Any) -> None:
                try:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    moisture = payload.get("moisture_pct")
                    raw = payload.get("moisture_raw")
                    if moisture is None:
                        if raw is None:
                            raise ValueError("Payload must include moisture_pct or moisture_raw")
                        raw = float(raw)
                        dry = float(os.getenv("AQUALOOP_DRY_RAW", "3000"))
                        wet = float(os.getenv("AQUALOOP_WET_RAW", "1200"))
                        if dry == wet:
                            raise ValueError("Dry and wet calibration values cannot be equal")
                        moisture = max(0.0, min(100.0, (dry - raw) / (dry - wet) * 100.0))
                    reading = {
                        "timestamp": payload.get("timestamp"),
                        "device_id": payload.get("device_id", "esp32_aqualoop_01"),
                        "zone_id": payload.get("zone_id", "zone_1"),
                        "moisture_raw": raw,
                        "moisture_pct": float(moisture),
                        "flow_lpm": float(payload.get("flow_lpm", 0) or 0),
                        "temp_c": payload.get("temp_c"),
                        "humidity_pct": payload.get("humidity_pct"),
                        "rainfall_mm": float(payload.get("rainfall_mm", 0) or 0),
                        "source": "mqtt_live",
                        "notes": f"Received via MQTT topic {msg.topic}",
                    }
                    add_reading(reading)
                    with self._lock:
                        self.messages_received += 1
                except Exception as exc:
                    self.last_error = f"Invalid MQTT payload: {exc}"
                    add_event("mqtt_payload_error", self.last_error, "warning")

            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.on_message = on_message
            client.connect(host, int(port), keepalive=45)
            client.loop_start()
            self.client = client
            self.thread_started = True
            self.last_error = ""
            return True, "MQTT connection initiated. Wait for the broker handshake and incoming telemetry."
        except Exception as exc:
            self.last_error = str(exc)
            return False, f"Could not start MQTT: {exc}"

    def stop(self) -> None:
        if self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception:
                pass
        self.client = None
        self.thread_started = False
        self.connected = False

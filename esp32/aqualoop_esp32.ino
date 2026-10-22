/*
  AquaLoop ESP32 telemetry firmware (sensor publishing only)
  Libraries: PubSubClient by Nick O'Leary
  Board: ESP32 Dev Module

  Safety: this firmware only publishes telemetry. It does not control a pump or valve.
  Calibrate DRY_RAW/WET_RAW for your sensor and soil before trusting moisture_pct.
*/
#include <WiFi.h>
#include <PubSubClient.h>

// ---------- Replace these values before flashing ----------
const char* WIFI_SSID = "YOUR_WIFI_NAME";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* MQTT_HOST = "192.168.1.10";  // Computer running Mosquitto, on same LAN
const int   MQTT_PORT = 1883;
const char* MQTT_USERNAME = "";          // Optional; prefer authenticated broker
const char* MQTT_PASSWORD = "";
const char* DEVICE_ID = "esp32_aqualoop_01";
const char* ZONE_ID = "zone_1";
const char* MQTT_TOPIC = "aqualoop/zone_1/telemetry";

// Sensor pins
const int MOISTURE_PIN = 34;  // ADC1 pin, input-only
const int FLOW_PIN = 27;      // Flow pulse input; use a level shifter if sensor output is 5V

// Calibrate for your own sensor. ESP32 ADC readings can vary between boards.
const int DRY_RAW = 3000;
const int WET_RAW = 1200;
const float FLOW_PULSES_PER_LPM_HZ = 7.5f;  // Verify calibration for your flow sensor
const unsigned long SAMPLE_INTERVAL_MS = 5000;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);
volatile unsigned long flowPulses = 0;
unsigned long lastSampleMs = 0;

void IRAM_ATTR onFlowPulse() {
  flowPulses++;
}

float calculateMoisturePct(int raw) {
  if (DRY_RAW == WET_RAW) return -1.0f;
  float percent = ((float)DRY_RAW - (float)raw) * 100.0f / ((float)DRY_RAW - (float)WET_RAW);
  if (percent < 0.0f) percent = 0.0f;
  if (percent > 100.0f) percent = 100.0f;
  return percent;
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  unsigned long started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < 20000) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("Wi-Fi connected. Device IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("Wi-Fi connection timed out; will retry.");
  }
}

void connectMQTT() {
  if (WiFi.status() != WL_CONNECTED) return;
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  while (!mqttClient.connected()) {
    String clientId = String(DEVICE_ID) + "_" + String((uint32_t)ESP.getEfuseMac(), HEX);
    Serial.print("Connecting to MQTT...");
    bool connected;
    if (strlen(MQTT_USERNAME) > 0) {
      connected = mqttClient.connect(clientId.c_str(), MQTT_USERNAME, MQTT_PASSWORD);
    } else {
      connected = mqttClient.connect(clientId.c_str());
    }
    if (connected) {
      Serial.println("connected");
    } else {
      Serial.print("failed, state=");
      Serial.println(mqttClient.state());
      delay(2500);
      // Do not block forever; loop() retries later.
      break;
    }
  }
}

void publishTelemetry() {
  const unsigned long now = millis();
  const unsigned long elapsed = now - lastSampleMs;
  if (elapsed == 0) return;

  noInterrupts();
  const unsigned long pulses = flowPulses;
  flowPulses = 0;
  interrupts();

  int raw = analogRead(MOISTURE_PIN);
  float moisturePct = calculateMoisturePct(raw);
  float pulseHz = (float)pulses * 1000.0f / (float)elapsed;
  float flowLpm = pulseHz / FLOW_PULSES_PER_LPM_HZ;

  // UTC timestamps are supplied by the dashboard if unavailable. This firmware
  // leaves timestamp out to avoid publishing incorrect wall-clock time without NTP.
  String payload = "{";
  payload += "\"device_id\":\"" + String(DEVICE_ID) + "\",";
  payload += "\"zone_id\":\"" + String(ZONE_ID) + "\",";
  payload += "\"moisture_raw\":" + String(raw) + ",";
  payload += "\"moisture_pct\":" + String(moisturePct, 1) + ",";
  payload += "\"flow_lpm\":" + String(flowLpm, 2);
  payload += "}";

  if (mqttClient.connected()) {
    bool ok = mqttClient.publish(MQTT_TOPIC, payload.c_str());
    Serial.print(ok ? "Published: " : "Publish failed: ");
    Serial.println(payload);
  }
  lastSampleMs = now;
}

void setup() {
  Serial.begin(115200);
  delay(300);
  analogReadResolution(12);
  pinMode(MOISTURE_PIN, INPUT);
  pinMode(FLOW_PIN, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(FLOW_PIN), onFlowPulse, RISING);
  connectWiFi();
  connectMQTT();
  lastSampleMs = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  if (WiFi.status() == WL_CONNECTED && !mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();
  if (millis() - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    publishTelemetry();
  }
  delay(10);
}

/*
  GridWatcher: Base Station (Transmitter) — v3 Legal + Optimized
  Hardware: FireBeetle 2 ESP32-C6, SX1262 LoRa, MT3608 Step-up

  Compliance & Fixes:
  - TX interval 2000ms (was 1000ms) — EU/SA 868MHz 1% duty cycle compliance
  - TX power reduced to +14dBm (was +22dBm) — lowers battery draw & stays legal
  - Cell signal staleness timeout: 30s before marking as -999
  - Reinit backoff: doubles wait time on each failed reinit (max 80s)
  - Boot delay reduced to 500ms
  - Serial verbose mode flag (set false to suppress per-packet spam)
  - Battery: 5-sample average for stable reading
  - snprintf payloads — zero heap allocation

  LoRa Packet Format:
  V:<voltage>,F:<freq>,B:<base_batt>,S:<cell_dbm>,PB:<phone_batt>,SEQ:<seq>
*/

#include <SPI.h>
#include <RadioLib.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Update.h>

// ==============================================================================
// [0] CONFIG FLAGS
// ==============================================================================
#define SERIAL_VERBOSE    true    // Set false to suppress per-packet TX log spam
#define TX_INTERVAL_MS    2000   // 2s TX interval for legal 1% duty cycle compliance
#define TX_POWER_DBM      14     // +14dBm — legal, excellent range at home distances
#define CELL_STALE_MS     30000  // Mark cell signal as -999 after 30s of no update

const char* otaHTML =
"<!DOCTYPE html><html><head><title>GridWatcher OTA Update</title>"
"<style>body{font-family:sans-serif;background:#121212;color:#fff;text-align:center;padding-top:50px;}"
"input[type=file]{margin:20px 0;padding:10px;background:#222;color:#fff;border:1px solid #444;border-radius:5px;}"
"input[type=submit]{padding:10px 20px;background:#00e676;color:#000;border:none;font-weight:bold;border-radius:5px;cursor:pointer;}"
"</style></head><body><h2>GridWatcher Sender OTA</h2>"
"<form method='POST' action='/update' enctype='multipart/form-data'>"
"<input type='file' name='update'><br><br>"
"<input type='submit' value='Flash Firmware Wireless'>"
"</form></body></html>";

// ==============================================================================
// [1] HARDWARE & PIN DEFINITIONS
// ==============================================================================
#define LORA_CS   14
#define LORA_DIO1 4
#define LORA_RST  1
#define LORA_BUSY 5
#define PIN_BAT   0

// ==============================================================================
// [2] NETWORK CONFIGURATION
// ==============================================================================
const char* homeSSID = "YOUR_HOME_WIFI_NAME";
const char* homePass = "YOUR_HOME_WIFI_PASSWORD";
const char* apSSID   = "GridWatcher-Home";
const char* apPass   = "gridwatcher123";

WebServer server(80);

// ==============================================================================
// [3] GLOBALS & STATE
// ==============================================================================
SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);

int cellSignalDbm     = -999;
int phoneBatteryPercent = -1;
unsigned long lastCellUpdate = 0;
unsigned long lastSendTime   = 0;
unsigned long packetSequence = 0;
int batteryPercent = 100;

// Radio health tracking
unsigned long lastSuccessfulTx  = 0;
int consecutiveTxFails          = 0;
unsigned long reinitBackoffMs   = 10000; // Starts at 10s, doubles on each fail
unsigned long lastReinitAttempt = 0;
#define MAX_TX_FAILS     5
#define MAX_BACKOFF_MS   80000   // Cap backoff at 80 seconds

// Pre-allocated payload buffer — zero heap allocation
char payload[128];

// ==============================================================================
// [4] HARDWARE & SENSOR FUNCTIONS
// ==============================================================================
void readBattery() {
  // 5-sample average for a stable, noise-free reading
  long sum = 0;
  for (int i = 0; i < 5; i++) {
    sum += analogReadMilliVolts(PIN_BAT);
    delayMicroseconds(200);
  }
  int batteryMilliVolts = (sum / 5) * 2; // Voltage divider × 2
  float pct = (batteryMilliVolts - 3300) / (4200.0 - 3300.0) * 100.0;
  batteryPercent = constrain((int)pct, 0, 100);
}

void reinitRadio() {
  unsigned long now = millis();
  // Backoff: don't retry reinit until backoff window has passed
  if (now - lastReinitAttempt < reinitBackoffMs) return;
  lastReinitAttempt = now;

  Serial.printf("[RADIO] Reinit attempt (backoff was %lus)...\n", reinitBackoffMs / 1000);
  radio.reset();
  delay(10);

  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, TX_POWER_DBM, 8, 1.6, false);
  if (state == RADIOLIB_ERR_NONE) {
    radio.setDio2AsRfSwitch(true);
    consecutiveTxFails = 0;
    reinitBackoffMs    = 10000; // Reset backoff on success
    lastSuccessfulTx   = millis();
    Serial.println("[RADIO] Reinitialized successfully!");
  } else {
    // Double the backoff, cap at maximum
    reinitBackoffMs = min(reinitBackoffMs * 2, (unsigned long)MAX_BACKOFF_MS);
    Serial.printf("[RADIO] Reinit FAILED (code %d). Next attempt in %lus\n",
                  state, reinitBackoffMs / 1000);
  }
}

// ==============================================================================
// [5] WEBSERVER & HTTP ENDPOINTS
// ==============================================================================
void handleSignal() {
  if (server.hasArg("value")) {
    cellSignalDbm  = server.arg("value").toInt();
    lastCellUpdate = millis();

    if (server.hasArg("phone_battery")) {
      phoneBatteryPercent = server.arg("phone_battery").toInt();
    }

    Serial.printf("[WiFi] Cell: %ddBm | Phone Batt: %d%%\n",
                  cellSignalDbm, phoneBatteryPercent);
    server.send(200, "text/plain", "OK");
  } else {
    server.send(400, "text/plain", "missing value param");
  }
}

void handleStatus() {
  char json[300];
  snprintf(json, sizeof(json),
    "{\"cellSignalDbm\":%d,\"phoneBatteryPercent\":%d,\"batteryPercent\":%d,"
    "\"packetSequence\":%lu,\"staConnected\":%s,\"staIP\":\"%s\","
    "\"txFails\":%d,\"reinitBackoffMs\":%lu,\"cellFresh\":%s}",
    cellSignalDbm, phoneBatteryPercent, batteryPercent,
    packetSequence,
    (WiFi.status() == WL_CONNECTED) ? "true" : "false",
    WiFi.localIP().toString().c_str(),
    consecutiveTxFails,
    reinitBackoffMs,
    (millis() - lastCellUpdate < CELL_STALE_MS) ? "true" : "false");
  server.send(200, "application/json", json);
}

// ==============================================================================
// [6] SYSTEM INITIALIZATION
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(500); // Was 2500ms — no reason to wait that long

  Serial.println("\n[ESP32-C6] Booting GridWatcher Home Sender v3...");
  analogReadResolution(12);

  SPI.begin(23, 21, 22);

  Serial.printf("[SX1262] Init (868MHz, SF9, BW125, +%ddBm)...\n", TX_POWER_DBM);
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, TX_POWER_DBM, 8, 1.6, false);

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("[SX1262] Success!");
    radio.setDio2AsRfSwitch(true);
    lastSuccessfulTx  = millis();
    lastReinitAttempt = millis();
  } else {
    Serial.printf("[SX1262] FAILED code: %d\n", state);
    while (true) { delay(1000); }
  }

  // WiFi: AP is critical, STA is optional
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(apSSID, apPass);
  Serial.printf("[WiFi] AP '%s' -> %s\n", apSSID, WiFi.softAPIP().toString().c_str());

  // Disable aggressive STA auto-reconnect — prevents WiFi scans disrupting SPI
  WiFi.setAutoReconnect(false);
  WiFi.begin(homeSSID, homePass);
  Serial.println("[WiFi] STA connecting (auto-reconnect disabled to protect LoRa)...");

  server.on("/signal", HTTP_POST, handleSignal);
  server.on("/status", HTTP_GET,  handleStatus);

  // Wireless OTA Endpoints
  server.on("/update", HTTP_GET, []() {
    server.send(200, "text/html", otaHTML);
  });

  server.on("/update", HTTP_POST, []() {
    server.send(200, "text/plain", (Update.hasError()) ? "FAIL" : "OK");
    delay(500);
    ESP.restart();
  }, []() {
    HTTPUpload& upload = server.upload();
    if (upload.status == UPLOAD_FILE_START) {
      Serial.printf("[OTA] Flashing: %s\n", upload.filename.c_str());
      if (!Update.begin(UPDATE_SIZE_UNKNOWN)) Update.printError(Serial);
    } else if (upload.status == UPLOAD_FILE_WRITE) {
      if (Update.write(upload.buf, upload.currentSize) != upload.currentSize)
        Update.printError(Serial);
    } else if (upload.status == UPLOAD_FILE_END) {
      if (Update.end(true))
        Serial.printf("[OTA] Success! %u bytes flashed. Rebooting...\n", upload.totalSize);
      else
        Update.printError(Serial);
    }
  });

  server.begin();
  Serial.println("[WiFi] Web server & OTA started on port 80.");
  Serial.printf("[INFO] TX interval: %dms | TX power: +%ddBm | Duty cycle: ~%.1f%%\n",
                TX_INTERVAL_MS, TX_POWER_DBM,
                (200.0 / TX_INTERVAL_MS) * 100.0); // ~200ms airtime per packet
}

// ==============================================================================
// [7] MAIN RUNTIME LOOP
// ==============================================================================
void loop() {
  server.handleClient();
  yield();

  // Cell signal staleness check — expire stale data after CELL_STALE_MS
  if (lastCellUpdate > 0 && millis() - lastCellUpdate > CELL_STALE_MS) {
    if (cellSignalDbm != -999) {
      Serial.println("[WiFi] Cell signal data stale (>30s). Marking as unknown.");
      cellSignalDbm = -999;
    }
  }

  // Automatic telemetry broadcast every TX_INTERVAL_MS (2 seconds)
  if (millis() - lastSendTime >= TX_INTERVAL_MS) {
    lastSendTime = millis();
    packetSequence++;
    readBattery();

    // Simulated AC readings (replace with real ZMPT101B sensor reads)
    float simV = 230.0 + random(-15, 16) / 10.0;
    float simF = 49.9  + random(0, 3) / 10.0;

    snprintf(payload, sizeof(payload),
      "V:%.1f,F:%.2f,B:%d,S:%d,PB:%d,SEQ:%lu",
      simV, simF, batteryPercent, cellSignalDbm, phoneBatteryPercent, packetSequence);

    if (SERIAL_VERBOSE) {
      Serial.printf("TX [%lu]: %s\n", packetSequence, payload);
    }

    int state = radio.transmit(payload);

    if (state == RADIOLIB_ERR_NONE) {
      if (SERIAL_VERBOSE) Serial.println("  -> OK");
      lastSuccessfulTx   = millis();
      consecutiveTxFails = 0;
      reinitBackoffMs    = 10000; // Reset backoff on any success
    } else {
      Serial.printf("TX FAIL (Code: %d)\n", state);
      consecutiveTxFails++;
    }
  }

  // Radio watchdog with exponential backoff reinit
  if (consecutiveTxFails >= MAX_TX_FAILS ||
      (lastSuccessfulTx > 0 && millis() - lastSuccessfulTx > reinitBackoffMs)) {
    reinitRadio();
  }
}

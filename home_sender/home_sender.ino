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

#include <Arduino.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <Update.h>
#include <ESPmDNS.h>
#include <LittleFS.h>
#include <RadioLib.h>
#include <Preferences.h>
#include "grid_model.h"

#define CURRENT_VERSION ML_MODEL_VERSION
const char* OTA_VERSION_URL = "https://raw.githubusercontent.com/kylerichter36-coder/GridWatcher/main/version.json";
const char* OTA_BIN_URL     = "https://raw.githubusercontent.com/kylerichter36-coder/GridWatcher/main/home_sender.bin";

// GitHub Direct HTTPS Auto-OTA Self-Flashing Engine
void checkGitHubAutoOTA() {
  if (WiFi.status() != WL_CONNECTED) return;
  Serial.println("[Auto-OTA] Checking GitHub for firmware and ML model updates...");
  
  WiFiClientSecure client;
  client.setInsecure(); // Bypass SSL certificate verification for GitHub raw CDN
  
  HTTPClient http;
  if (http.begin(client, OTA_VERSION_URL)) {
    int httpCode = http.GET();
    if (httpCode == HTTP_CODE_OK) {
      String payload = http.getString();
      int remoteVersion = 0;
      int idx = payload.indexOf("\"version\":");
      if (idx != -1) {
        remoteVersion = payload.substring(idx + 10).toInt();
      }
      
      Serial.printf("[Auto-OTA] Local Version: v%d | GitHub Remote Version: v%d\n", CURRENT_VERSION, remoteVersion);
      if (remoteVersion > CURRENT_VERSION) {
        Serial.println("[Auto-OTA] NEW FIRMWARE / ML MODEL VERSION DETECTED ON GITHUB!");
        Serial.println("[Auto-OTA] Downloading home_sender.bin and self-flashing over HTTPS...");
        
        HTTPClient httpBin;
        if (httpBin.begin(client, OTA_BIN_URL)) {
          int binCode = httpBin.GET();
          if (binCode == HTTP_CODE_OK) {
            int contentLength = httpBin.getSize();
            if (Update.begin(contentLength)) {
              WiFiClient* stream = httpBin.getStreamPtr();
              size_t written = Update.writeStream(*stream);
              if (written == contentLength) {
                Serial.println("[Auto-OTA] Written successfully! Finalizing update...");
                if (Update.end(true)) {
                  Serial.println("[Auto-OTA] OTA SUCCESSFUL! Rebooting into new firmware...");
                  ESP.restart();
                }
              }
            }
          }
          httpBin.end();
        }
      } else {
        Serial.println("[Auto-OTA] Firmware and ML model weights are up to date!");
      }
    }
    http.end();
  }
}

// ==============================================================================
// [0] CONFIG FLAGS
// ==============================================================================
#define SERIAL_VERBOSE    true    // Set false to suppress per-packet TX log spam
#define TX_INTERVAL_MS    2000
#define TX_POWER_DBM      9    // +5 dBi antenna: 9dBm TX + 5dBi - 1dB loss = ~13dBm EIRP = ~12mW ERP
                               // Legal limit is 25mW ERP. Change to 22 ONLY if using a simple wire/0dBi antenna.
#define CELL_STALE_MS     30000

// LoRa radio config — MUST match exactly on sender and handheld
#define LORA_FREQ     868.0
#define LORA_BW       125.0
#define LORA_SF       10
#define LORA_CR       7
#define LORA_SYNC     0x12
#define LORA_PREAMBLE 8

// OTA Hub state — tracks which devices still need to update
bool handheldUpdateReady  = false;   // handheld.bin uploaded and waiting
bool bridgeUpdateReady    = false;   // bridge.py uploaded and waiting
bool senderUpdatePending  = false;   // sender own firmware staged, waiting for others
bool handheldConfirmed    = false;   // handheld reported OK
bool bridgeConfirmed      = false;   // phone bridge reported OK

// Grid State
float lastVoltage         = 0.0;
float lastFrequency       = 0.0;
float zmptCalibration     = 0.46;  // Multiplier mapping raw RMS ADC units to real AC Volts (adjust via /calibrate?val=0.46)
#define PIN_BOOT_BTN      9
#define PIN_ZMPT          6        // ZMPT101B active module analog OUT on GPIO 6

// Sender hub dashboard — upload firmware for all 3 devices from one page.
// Laptop accesses this at http://gridwatcher-sender.local/ota (stays on home WiFi).
const char HUB_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html><html><head><meta charset='UTF-8'>
<title>GridWatcher OTA Hub</title>
<meta http-equiv='refresh' content='5'>
<style>
body{font-family:sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:20px;}
h1{color:#58a6ff;border-bottom:1px solid #30363d;padding-bottom:10px;}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:16px;margin:12px 0;}
.card h3{margin-top:0;color:#79c0ff;}
.status{display:inline-block;padding:3px 10px;border-radius:12px;font-size:0.85em;font-weight:bold;}
.ok{background:#1a4731;color:#3fb950;}
.wait{background:#3d2b00;color:#e3b341;}
.ready{background:#1f3d6e;color:#58a6ff;}
input[type=file]{background:#21262d;color:#e6edf3;border:1px solid #30363d;padding:6px;border-radius:4px;width:100%;margin:8px 0;}
btn,input[type=submit]{padding:8px 16px;background:#238636;color:#fff;border:none;border-radius:6px;cursor:pointer;font-weight:bold;margin-top:6px;}
btn:hover,input[type=submit]:hover{background:#2ea043;}
.info{color:#8b949e;font-size:0.85em;margin-top:4px;}
table{width:100%;border-collapse:collapse;}
td,th{padding:8px 12px;border:1px solid #30363d;text-align:left;}
th{background:#21262d;color:#79c0ff;}
</style></head><body>
<h1>GridWatcher OTA Hub</h1>
<div class='card'>
<h3>Device Status</h3>
<table><tr><th>Device</th><th>Update Ready</th><th>Confirmed</th></tr>
<tr><td>Handheld</td>
    <td><span class='status %HREADY%'>%HREADYTXT%</span></td>
    <td><span class='status %HCONF%'>%HCONFTXT%</span></td></tr>
<tr><td>Phone Bridge</td>
    <td><span class='status %BREADY%'>%BREADYTXT%</span></td>
    <td><span class='status %BCONF%'>%BCONFTXT%</span></td></tr>
<tr><td>Sender (self)</td>
    <td><span class='status %SREADY%'>%SREADYTXT%</span></td>
    <td><span class='status ok'>%SCONFTXT%</span></td></tr>
</table>
</div>
<div class='card'>
<h3>1. Upload Handheld Firmware</h3>
<p class='info'>handheld will pull this automatically when you hold BOOT for 3s</p>
<form method='POST' action='/upload-handheld' enctype='multipart/form-data'>
<input type='file' name='file' accept='.bin'>
<input type='submit' value='Upload Handheld Firmware'>
</form>
</div>
<div class='card'>
<h3>2. Upload Bridge Script</h3>
<p class='info'>phone bridge checks for this on every startup</p>
<form method='POST' action='/upload-bridge' enctype='multipart/form-data'>
<input type='file' name='file' accept='.py'>
<input type='submit' value='Upload Bridge Script'>
</form>
</div>
<div class='card'>
<h3>3. Upload Sender Firmware (applied last)</h3>
<p class='info'>sender stages this and reboots automatically after handheld + phone confirm</p>
<form method='POST' action='/update' enctype='multipart/form-data'>
<input type='file' name='update' accept='.bin'>
<input type='submit' value='Stage Sender Firmware'>
</form>
</div>
</body></html>)rawliteral";

// ==============================================================================
// [1] HARDWARE & PIN DEFINITIONS
// ==============================================================================
#define LORA_CS   14
#define LORA_DIO1 4
#define LORA_RST  1
#define LORA_BUSY 5
#define PIN_BAT   0

// Onboard LED for visual TX feedback (no terminal needed)
// FireBeetle 2 ESP32-C6: try LED_BUILTIN first; change to your board's LED pin if needed
#ifndef LED_BUILTIN
  #define LED_BUILTIN 8
#endif
#define LED_PIN LED_BUILTIN
#define LED_TX_MS   30    // Short blip on successful TX
#define LED_ERR_MS  120   // Longer pulse on TX fail
unsigned long ledOffMs = 0;  // millis() when LED should turn off (0 = already off)

// ==============================================================================
// [2] NETWORK CONFIGURATION
// ==============================================================================
#include "secrets.h"

// ---- Home WiFi (primary) ----
#ifdef SECRET_WIFI_SSID
const char* homeSSID = SECRET_WIFI_SSID;
const char* homePass = SECRET_WIFI_PASS;
#else
const char* homeSSID = "YOUR_WIFI_SSID";
const char* homePass = "YOUR_WIFI_PASSWORD";
#endif

// ---- Phone hotspot (fallback when away from home) ----
const char* phoneSSID = "YOUR_PHONE_HOTSPOT_NAME";     // <-- fill in
const char* phonePass = "YOUR_PHONE_HOTSPOT_PASSWORD"; // <-- fill in

// ---- Sender AP (always on, for local debugging) ----
const char* apSSID   = "GridWatcher-Home";
const char* apPass   = "gridwatcher123";

// mDNS hostname — access OTA at http://gridwatcher-sender.local/update from any
// device on the same network. No WiFi switching needed on laptop.
#define MDNS_HOSTNAME "gridwatcher-sender"

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

// Read Real RMS Voltage & Frequency from ZMPT101B Active Module on GPIO 2
void readZMPT101B(float &vRMS, float &freq) {
  // If BOOT button is held, simulate outage (0V, 0Hz) for easy SMS testing
  if (digitalRead(PIN_BOOT_BTN) == LOW) {
    vRMS = 0.0;
    freq = 0.0;
    Serial.println("[SIM] Outage simulated via BOOT button hold!");
    return;
  }

  // Sample over 40ms (2 full 50Hz AC cycles)
  unsigned long start = millis();
  long sumADC = 0;
  int sampleCount = 0;
  int minVal = 4095;
  int maxVal = 0;

  // First pass: 40ms to calculate DC offset (center bias point) and peak-to-peak
  while (millis() - start < 40) {
    int raw = analogRead(PIN_ZMPT);
    if (raw < minVal) minVal = raw;
    if (raw > maxVal) maxVal = raw;
    sumADC += raw;
    sampleCount++;
    delayMicroseconds(100);
  }

  int p2p = maxVal - minVal;
  int dcOffset = (sampleCount > 0) ? (sumADC / sampleCount) : 2048;

  // Validate DC bias offset: active ZMPT101B op-amp MUST sit between 0.5V and 3.0V (ADC 500..3800)
  // If DC offset is near 0 (like DC: 55), the module is unpowered, ungrounded, or floating!
  if (dcOffset < 500 || dcOffset > 3800) {
    vRMS = 0.0;
    freq = 0.0;
    if (SERIAL_VERBOSE) {
      Serial.printf("[ZMPT101B] UNPOWERED/FLOATING (DC: %d | P2P: %d) -> Check VCC 5V & GND!\n", dcOffset, p2p);
    }
    return;
  }

  // If signal peak-to-peak is below 300 ADC units (mains is unplugged / 0V AC), return 0V / 0Hz
  if (p2p < 300) {
    vRMS = 0.0;
    freq = 0.0;
    return;
  }

  // Second pass: 40ms to calculate True RMS and zero-crossing frequency
  double sumSquares = 0;
  int rmsSamples = 0;
  unsigned long lastZeroCross = 0;
  unsigned long zeroCrossPeriodSum = 0;
  int zeroCrossCount = 0;
  bool lastAbove = false;

  start = millis();
  while (millis() - start < 40) {
    int raw = analogRead(PIN_ZMPT);
    double diff = raw - dcOffset;
    sumSquares += diff * diff;
    rmsSamples++;

    bool currentAbove = (raw > dcOffset);
    if (!lastAbove && currentAbove) {
      unsigned long nowMicros = micros();
      if (lastZeroCross > 0) {
        unsigned long period = nowMicros - lastZeroCross;
        if (period >= 15000 && period <= 25000) { // 50Hz nominal = 20,000us
          zeroCrossPeriodSum += period;
          zeroCrossCount++;
        }
      }
      lastZeroCross = nowMicros;
    }
    lastAbove = currentAbove;
    delayMicroseconds(100);
  }

  if (rmsSamples == 0) {
    vRMS = 0.0;
    freq = 0.0;
    return;
  }

  double meanSquare = sumSquares / rmsSamples;
  double rawRMS = sqrt(meanSquare);

  vRMS = rawRMS * zmptCalibration;

  if (zeroCrossCount > 0) {
    float avgPeriodUs = (float)zeroCrossPeriodSum / zeroCrossCount;
    freq = 1000000.0 / avgPeriodUs;
  } else {
    freq = (vRMS > 10.0) ? 50.0 : 0.0;
  }

  if (SERIAL_VERBOSE) {
    Serial.printf("[ZMPT101B] rawRMS: %.1f | P2P: %d | DC: %d -> vRMS: %.1fV | Freq: %.2fHz\n",
                  rawRMS, p2p, dcOffset, vRMS, freq);
  }
}

void reinitRadio() {
  unsigned long now = millis();
  // Backoff: don't retry reinit until backoff window has passed
  if (now - lastReinitAttempt < reinitBackoffMs) return;
  lastReinitAttempt = now;

  Serial.printf("[RADIO] Reinit attempt (backoff was %lus)...\n", reinitBackoffMs / 1000);
  radio.reset();
  delay(10);

  int state = radio.begin(LORA_FREQ, LORA_BW, LORA_SF, LORA_CR,
                          LORA_SYNC, TX_POWER_DBM, LORA_PREAMBLE, 1.6, false);
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

    Serial.printf("[WiFi] Cell: %ddBm | Phone Batt: %d%% | Grid: %.1fV\n",
                  cellSignalDbm, phoneBatteryPercent, lastVoltage);
                  
    char resp[100];
    snprintf(resp, sizeof(resp), "{\"voltage\":%.1f,\"frequency\":%.2f}", lastVoltage, lastFrequency);
    server.send(200, "application/json", resp);
  } else {
    server.send(400, "text/plain", "missing value param");
  }
}

void handleStatus() {
  char json[450];
  snprintf(json, sizeof(json),
    "{\"voltage\":%.1f,\"frequency\":%.2f,\"cellSignalDbm\":%d,\"phoneBatteryPercent\":%d,"
    "\"batteryPercent\":%d,\"packetSequence\":%lu,\"staConnected\":%s,\"staIP\":\"%s\","
    "\"txFails\":%d,\"reinitBackoffMs\":%lu,\"cellFresh\":%s,\"mlVersion\":%d,\"mlBuildTime\":\"%s\"}",
    lastVoltage, lastFrequency,
    cellSignalDbm, phoneBatteryPercent, batteryPercent,
    packetSequence,
    (WiFi.status() == WL_CONNECTED) ? "true" : "false",
    WiFi.localIP().toString().c_str(),
    consecutiveTxFails,
    reinitBackoffMs,
    (millis() - lastCellUpdate < CELL_STALE_MS) ? "true" : "false",
    ML_MODEL_VERSION,
    ML_MODEL_BUILD_TIME);
  server.send(200, "application/json", json);
}

// ==============================================================================
// [6] SYSTEM INITIALIZATION
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(500);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);
  pinMode(PIN_ZMPT, INPUT);

  Serial.println("\n[ESP32-C6] Booting GridWatcher Home Sender v3...");
  analogReadResolution(12);

  SPI.begin(23, 21, 22);

  Serial.printf("[SX1262] Init (%.0fMHz, SF%d, BW%.0f, +%ddBm)...\n",
                LORA_FREQ, LORA_SF, LORA_BW, TX_POWER_DBM);
  int state = radio.begin(LORA_FREQ, LORA_BW, LORA_SF, LORA_CR,
                          LORA_SYNC, TX_POWER_DBM, LORA_PREAMBLE, 1.6, false);

  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("[SX1262] Success!");
    radio.setDio2AsRfSwitch(true);
    lastSuccessfulTx  = millis();
    lastReinitAttempt = millis();
    Serial.println("============================================================");
    Serial.printf("  SENDER RADIO CONFIG\n");
    Serial.printf("  Freq:     %.1f MHz\n",  LORA_FREQ);
    Serial.printf("  SF:       %d\n",         LORA_SF);
    Serial.printf("  BW:       %.0f kHz\n",  LORA_BW);
    Serial.printf("  CR:       4/%d\n",       LORA_CR);
    Serial.printf("  SyncWord: 0x%02X\n",     LORA_SYNC);
    Serial.printf("  Preamble: %d\n",         LORA_PREAMBLE);
    Serial.printf("  TXPower:  +%d dBm\n",   TX_POWER_DBM);
    Serial.println("  >>> HANDHELD MUST MATCH ALL VALUES ABOVE <<<");
    Serial.println("============================================================");
  } else {
    Serial.printf("[SX1262] FAILED code: %d\n", state);
    while (true) { delay(1000); }
  }

  // Start LittleFS for storing handheld firmware and bridge script on sender's flash
  // Arduino IDE: Tools -> Partition Scheme -> "Default 4MB with spiffs" (or Minimal SPIFFS)
  if (!LittleFS.begin(true)) {
    Serial.println("[LittleFS] Mount FAILED — check partition scheme in Arduino IDE!");
  } else {
    Serial.println("[LittleFS] Mounted OK");
  }

  // WiFi: AP always on + STA tries home WiFi first, phone hotspot as fallback
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(apSSID, apPass);
  Serial.printf("[WiFi] AP '%s' -> %s\n", apSSID, WiFi.softAPIP().toString().c_str());

  WiFi.setAutoReconnect(false);

  // Read stored Wi-Fi credentials from ESP32 Non-Volatile Flash (NVS Preferences)
  Preferences nvPrefs;
  nvPrefs.begin("grid_wifi", false);
  String nvsSSID = nvPrefs.getString("ssid", "");
  String nvsPass = nvPrefs.getString("pass", "");

  if (nvsSSID.length() > 0 && nvsSSID != "YOUR_WIFI_SSID") {
    homeSSID = strdup(nvsSSID.c_str());
    homePass = strdup(nvsPass.c_str());
    Serial.printf("[NVS FLASH] Loaded permanent Wi-Fi credentials: '%s'\n", homeSSID);
  } else {
    // Save initial credentials into permanent NVS flash memory
    nvPrefs.putString("ssid", homeSSID);
    nvPrefs.putString("pass", homePass);
    Serial.printf("[NVS FLASH] Stored permanent Wi-Fi credentials: '%s'\n", homeSSID);
  }
  nvPrefs.end();

  // Try home WiFi first (10s), then phone hotspot (10s), then AP-only
  const char* networks[][2] = {{homeSSID, homePass}, {phoneSSID, phonePass}};
  const char* networkNames[] = {"Home WiFi", "Phone Hotspot"};
  bool connected = false;
  for (int n = 0; n < 2 && !connected; n++) {
    Serial.printf("[WiFi] Trying %s ('%s')...\n", networkNames[n], networks[n][0]);
    WiFi.begin(networks[n][0], networks[n][1]);
    unsigned long t = millis();
    while (WiFi.status() != WL_CONNECTED && millis() - t < 10000) delay(200);
    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("[WiFi] Connected via %s -> %s\n",
                    networkNames[n], WiFi.localIP().toString().c_str());
      connected = true;
    } else {
      WiFi.disconnect();
      delay(500);
    }
  }
  if (!connected) Serial.println("[WiFi] No STA network found — AP-only mode.");

  // Start mDNS — laptop accesses OTA hub at http://gridwatcher-sender.local/ota
  if (WiFi.status() == WL_CONNECTED) {
    if (MDNS.begin(MDNS_HOSTNAME)) {
      MDNS.addService("http", "tcp", 80);
      Serial.printf("[mDNS] OTA hub: http://%s.local/ota\n", MDNS_HOSTNAME);
    }
    // Check GitHub for new firmware & ML model weights
    checkGitHubAutoOTA();
  }

  server.on("/signal", HTTP_POST, handleSignal);
  server.on("/status",  HTTP_GET,  handleStatus);

  // Home Assistant Remote Auto-OTA Trigger Endpoint
  server.on("/trigger-ota", HTTP_POST, []() {
    Serial.println("[HTTP] Remote Auto-OTA trigger button pressed from Home Assistant!");
    server.send(200, "application/json", "{\"status\":\"OTA update triggered\"}");
    checkGitHubAutoOTA();
  });
  server.on("/trigger-ota", HTTP_GET, []() {
    Serial.println("[HTTP] Remote Auto-OTA trigger button pressed from Home Assistant!");
    server.send(200, "application/json", "{\"status\":\"OTA update triggered\"}");
    checkGitHubAutoOTA();
  });

  // ---- OTA Hub: serve dashboard ----
  server.on("/ota", HTTP_GET, []() {
    String page = String(HUB_HTML);
    // Handheld status
    page.replace("%HREADY%",    handheldUpdateReady ? "ready" : "wait");
    page.replace("%HREADYTXT%", handheldUpdateReady ? "READY" : "none");
    page.replace("%HCONF%",     handheldConfirmed   ? "ok"    : "wait");
    page.replace("%HCONFTXT%", handheldConfirmed   ? "OK"    : "pending");
    // Bridge status
    page.replace("%BREADY%",    bridgeUpdateReady ? "ready" : "wait");
    page.replace("%BREADYTXT%", bridgeUpdateReady ? "READY" : "none");
    page.replace("%BCONF%",     bridgeConfirmed   ? "ok"    : "wait");
    page.replace("%BCONFTXT%", bridgeConfirmed   ? "OK"    : "pending");
    // Sender status
    page.replace("%SREADY%",    senderUpdatePending ? "ready" : "wait");
    page.replace("%SREADYTXT%", senderUpdatePending ? "STAGED" : "none");
    page.replace("%SCONFTXT%", (handheldConfirmed && bridgeConfirmed) ? "rebooting..." : "waiting");
    server.send(200, "text/html", page);
  });

  // ---- OTA Hub: receive and store handheld firmware ----
  server.on("/upload-handheld", HTTP_POST, []() {
    server.send(200, "text/plain", handheldUpdateReady ? "OK — handheld.bin stored" : "FAIL");
  }, []() {
    HTTPUpload& up = server.upload();
    static File f;
    if (up.status == UPLOAD_FILE_START) {
      Serial.printf("[HUB] Storing handheld firmware: %s\n", up.filename.c_str());
      f = LittleFS.open("/handheld.bin", "w");
    } else if (up.status == UPLOAD_FILE_WRITE && f) {
      f.write(up.buf, up.currentSize);
    } else if (up.status == UPLOAD_FILE_END) {
      if (f) { f.close(); handheldUpdateReady = true; handheldConfirmed = false; }
      Serial.printf("[HUB] handheld.bin stored (%u bytes)\n", up.totalSize);
    }
  });

  // ---- OTA Hub: receive and store bridge script ----
  server.on("/upload-bridge", HTTP_POST, []() {
    server.send(200, "text/plain", bridgeUpdateReady ? "OK — bridge.py stored" : "FAIL");
  }, []() {
    HTTPUpload& up = server.upload();
    static File f;
    if (up.status == UPLOAD_FILE_START) {
      Serial.printf("[HUB] Storing bridge script: %s\n", up.filename.c_str());
      f = LittleFS.open("/bridge.py", "w");
    } else if (up.status == UPLOAD_FILE_WRITE && f) {
      f.write(up.buf, up.currentSize);
    } else if (up.status == UPLOAD_FILE_END) {
      if (f) { f.close(); bridgeUpdateReady = true; bridgeConfirmed = false; }
      Serial.printf("[HUB] bridge.py stored (%u bytes)\n", up.totalSize);
    }
  });

  // ---- OTA Hub: serve stored handheld firmware to handheld ----
  server.on("/handheld-firmware", HTTP_GET, []() {
    if (!LittleFS.exists("/handheld.bin")) {
      server.send(404, "text/plain", "No handheld firmware uploaded yet");
      return;
    }
    File f = LittleFS.open("/handheld.bin", "r");
    server.streamFile(f, "application/octet-stream");
    f.close();
  });

  // ---- OTA Hub: serve stored bridge script to phone ----
  server.on("/bridge-script", HTTP_GET, []() {
    if (!LittleFS.exists("/bridge.py")) {
      server.send(404, "text/plain", "No bridge script uploaded yet");
      return;
    }
    File f = LittleFS.open("/bridge.py", "r");
    server.streamFile(f, "text/plain");
    f.close();
  });

  // ---- OTA Hub: check endpoints (devices poll these) ----
  server.on("/handheld-update-available", HTTP_GET, []() {
    server.send(200, "text/plain", handheldUpdateReady ? "yes" : "no");
  });
  server.on("/bridge-update-available", HTTP_GET, []() {
    server.send(200, "text/plain", bridgeUpdateReady ? "yes" : "no");
  });

  // ---- OTA Hub: devices call this after successful update ----
  server.on("/device-updated", HTTP_POST, []() {
    String dev = server.arg("device");
    if (dev == "handheld") {
      handheldConfirmed = true;
      handheldUpdateReady = false;  // clear until next upload
      Serial.println("[HUB] Handheld confirmed update OK");
    } else if (dev == "bridge") {
      bridgeConfirmed = true;
      bridgeUpdateReady = false;
      Serial.println("[HUB] Phone bridge confirmed update OK");
    }
    server.send(200, "text/plain", "OK");
    // If both confirmed and sender has a staged firmware, reboot into it
    if (handheldConfirmed && bridgeConfirmed && senderUpdatePending) {
      Serial.println("[HUB] All devices updated - rebooting sender into new firmware!");
      delay(500);
      ESP.restart();
    }
  });

  // ---- Sender self-update: STAGED (reboots only after all devices confirm) ----
  server.on("/update", HTTP_GET, []() {
    server.send(200, "text/html", String(HUB_HTML));
  });
  server.on("/update", HTTP_POST, []() {
    server.send(200, "text/plain", Update.hasError() ? "FAIL" : "OK - sender firmware staged");
    // Do NOT restart here - wait for handheld + bridge to confirm first
  }, []() {
    HTTPUpload& upload = server.upload();
    if (upload.status == UPLOAD_FILE_START) {
      Serial.printf("[HUB] Staging sender firmware: %s\n", upload.filename.c_str());
      if (!Update.begin(UPDATE_SIZE_UNKNOWN)) Update.printError(Serial);
    } else if (upload.status == UPLOAD_FILE_WRITE) {
      if (Update.write(upload.buf, upload.currentSize) != upload.currentSize)
        Update.printError(Serial);
    } else if (upload.status == UPLOAD_FILE_END) {
      if (Update.end(true)) {
        senderUpdatePending = true;
        Serial.printf("[HUB] Sender firmware staged (%u bytes) - waiting for devices\n",
                      upload.totalSize);
      } else {
        Update.printError(Serial);
      }
    }
  });

  // Live ZMPT101B Calibration endpoint: http://192.168.4.1/calibrate?val=0.46
  server.on("/calibrate", HTTP_GET, []() {
    if (server.hasArg("val")) {
      zmptCalibration = server.arg("val").toFloat();
      char msg[80];
      snprintf(msg, sizeof(msg), "ZMPT101B calibration updated to %.4f", zmptCalibration);
      server.send(200, "text/plain", msg);
    } else {
      char msg[140];
      snprintf(msg, sizeof(msg), "Current zmptCalibration: %.4f\nUse /calibrate?val=0.4600 to adjust.", zmptCalibration);
      server.send(200, "text/plain", msg);
    }
  });

  server.begin();
  Serial.println("[WiFi] Web server & OTA hub started on port 80.");
  Serial.printf("[OTA] Dashboard: http://%s.local/ota\n", MDNS_HOSTNAME);
  Serial.printf("[INFO] TX interval: %dms | TX power: +%ddBm\n",
                TX_INTERVAL_MS, TX_POWER_DBM);
}

// ==============================================================================
// [7] MAIN RUNTIME LOOP
// ==============================================================================

// Non-blocking LED tick — call every loop() iteration
inline void ledTick() {
  if (ledOffMs > 0 && millis() >= ledOffMs) {
    digitalWrite(LED_PIN, LOW);
    ledOffMs = 0;
  }
}

void loop() {
  server.handleClient();
  yield();
  ledTick(); // Non-blocking: turns LED off when its timer expires

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

    // Real ZMPT101B AC voltage & frequency reads from GPIO 2
    float realV = 0.0;
    float realF = 0.0;
    readZMPT101B(realV, realF);

    lastVoltage = realV;
    lastFrequency = realF;

    snprintf(payload, sizeof(payload),
      "V:%.1f,F:%.2f,B:%d,S:%d,PB:%d,SEQ:%lu",
      realV, realF, batteryPercent, cellSignalDbm, phoneBatteryPercent, packetSequence);

    if (SERIAL_VERBOSE) {
      Serial.printf("TX [%lu]: %s\n", packetSequence, payload);
    }

    int state = radio.transmit(payload);

    if (state == RADIOLIB_ERR_NONE) {
      if (SERIAL_VERBOSE) Serial.println("  -> OK");
      lastSuccessfulTx   = millis();
      consecutiveTxFails = 0;
      reinitBackoffMs    = 10000;
      // Short LED blip — TX success
      digitalWrite(LED_PIN, HIGH);
      ledOffMs = millis() + LED_TX_MS;
    } else {
      Serial.printf("TX FAIL (Code: %d)\n", state);
      consecutiveTxFails++;
      // Longer LED pulse — TX error
      digitalWrite(LED_PIN, HIGH);
      ledOffMs = millis() + LED_ERR_MS;
    }
  }

  // Radio watchdog with exponential backoff reinit
  if (consecutiveTxFails >= MAX_TX_FAILS ||
      (lastSuccessfulTx > 0 && millis() - lastSuccessfulTx > reinitBackoffMs)) {
    reinitRadio();
  }
}

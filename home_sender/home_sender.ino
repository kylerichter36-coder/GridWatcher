/*
  GridWatcher: Base Station (Transmitter)
  Hardware: FireBeetle 2 ESP32-C6, SX1262 LoRa, MT3608 Step-up
  
  Fixes applied:
  - Replaced String concatenation with snprintf (prevents heap fragmentation crash)
  - Added radio TX timeout recovery (prevents permanent hang on stuck DIO1)
  - Disabled WiFi STA auto-reconnect (prevents background scan interference)
  - Added watchdog-safe yield() calls

  LoRa Packet Format:
  V:<voltage>,F:<freq>,B:<base_batt>,S:<cell_dbm>,PB:<phone_batt>,SEQ:<seq>
*/

#include <SPI.h>
#include <RadioLib.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Update.h>

const char* otaHTML = 
"<!DOCTYPE html><html><head><title>GridWatcher OTA Update</title>"
"<style>body{font-family:sans-serif;background:#121212;color:#fff;text-align:center;padding-top:50px;}"
"input[type=file]{margin:20px 0;padding:10px;background:#222;color:#fff;border:1px solid #444;border-radius:5px;}"
"input[type=submit]{padding:10px 20px;background:#00e676;color:#000;border:none;font-weight:bold;border-radius:5px;cursor:pointer;}"
"</style></head><body><h2>GridWatcher Sender Firmware OTA</h2>"
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

#define PIN_BAT 0

// ==============================================================================
// [2] NETWORK CONFIGURATION (DUAL MODE WIFI)
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

int cellSignalDbm = -999;
int phoneBatteryPercent = -1;
unsigned long lastCellUpdate = 0;
unsigned long lastSendTime = 0;
unsigned long packetSequence = 0;
int batteryPercent = 100;

// Radio health tracking
unsigned long lastSuccessfulTx = 0;
int consecutiveTxFails = 0;
#define MAX_TX_FAILS 5          // Reinitialize radio after this many consecutive failures
#define TX_WATCHDOG_MS 10000    // If no successful TX in 10s, force radio reset

// Pre-allocated payload buffer (avoids String heap fragmentation)
char payload[128];

// ==============================================================================
// [4] HARDWARE & SENSOR FUNCTIONS
// ==============================================================================
void readBattery() {
  int mv = analogReadMilliVolts(PIN_BAT);
  int batteryMilliVolts = mv * 2;
  float pct = (batteryMilliVolts - 3300) / (4200.0 - 3300.0) * 100.0;
  batteryPercent = constrain((int)pct, 0, 100);
}

/**
 * Emergency radio reinitialization.
 * Called when the SX1262 gets stuck (missed interrupt, TX hang, etc.)
 */
void reinitRadio() {
  Serial.println("[RADIO] Reinitializing SX1262 after TX failure...");
  
  // Hard reset the module via its RST pin
  radio.reset();
  delay(10);
  
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 22, 8, 1.6, false);
  if (state == RADIOLIB_ERR_NONE) {
    radio.setDio2AsRfSwitch(true);
    consecutiveTxFails = 0;
    Serial.println("[RADIO] Reinitialized successfully!");
  } else {
    Serial.print("[RADIO] Reinit FAILED, code: ");
    Serial.println(state);
  }
}

// ==============================================================================
// [5] WEBSERVER & HTTP ENDPOINTS
// ==============================================================================
void handleSignal() {
  if (server.hasArg("value")) {
    cellSignalDbm = server.arg("value").toInt();
    lastCellUpdate = millis();
    Serial.print("[WiFi] Cell signal received: ");
    Serial.print(cellSignalDbm);
    
    if (server.hasArg("phone_battery")) {
      phoneBatteryPercent = server.arg("phone_battery").toInt();
      Serial.print(" | Phone Batt: ");
      Serial.print(phoneBatteryPercent);
      Serial.print("%");
    }
    Serial.println();
    
    server.send(200, "text/plain", "OK");
  } else {
    server.send(400, "text/plain", "missing value param");
  }
}

void handleStatus() {
  // Use snprintf instead of String concatenation
  char json[256];
  snprintf(json, sizeof(json),
    "{\"cellSignalDbm\":%d,\"phoneBatteryPercent\":%d,\"batteryPercent\":%d,"
    "\"packetSequence\":%lu,\"staConnected\":%s,\"staIP\":\"%s\",\"txFails\":%d}",
    cellSignalDbm, phoneBatteryPercent, batteryPercent,
    packetSequence,
    (WiFi.status() == WL_CONNECTED) ? "true" : "false",
    WiFi.localIP().toString().c_str(),
    consecutiveTxFails);
  server.send(200, "application/json", json);
}

// ==============================================================================
// [6] SYSTEM INITIALIZATION
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(2500); 

  Serial.println("\n[ESP32-C6] Booting GridWatcher Home Sender...");
  analogReadResolution(12);
  
  SPI.begin(23, 21, 22);

  Serial.print("[SX1262] Initializing Radio (868MHz, SF9, BW125, +22dBm) ... ");
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 22, 8, 1.6, false);
  
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("Success!");
    radio.setDio2AsRfSwitch(true);
    lastSuccessfulTx = millis();
  } else {
    Serial.print("Failed with code: ");
    Serial.println(state);
    Serial.println("Check SPI wiring and pin configurations.");
    while (true) { delay(1000); } // Halt on RF failure
  }
  
  Serial.println("Setup complete. Starting transmission loop...");

  // Initialize WiFi - AP mode is critical, STA is optional
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(apSSID, apPass);
  Serial.print("[WiFi] AP started: '");
  Serial.print(apSSID);
  Serial.print("' -> IP: ");
  Serial.println(WiFi.softAPIP());

  // Attempt STA connection but disable aggressive auto-reconnect
  // This prevents background WiFi scans from interfering with LoRa SPI timing
  WiFi.setAutoReconnect(false);
  WiFi.begin(homeSSID, homePass);
  Serial.println("[WiFi] STA connecting (auto-reconnect disabled to protect LoRa)...");

  server.on("/signal", HTTP_POST, handleSignal);
  server.on("/status", HTTP_GET, handleStatus);
  
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
      Serial.printf("[OTA] Flashing started: %s\n", upload.filename.c_str());
      if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
        Update.printError(Serial);
      }
    } else if (upload.status == UPLOAD_FILE_WRITE) {
      if (Update.write(upload.buf, upload.currentSize) != upload.currentSize) {
        Update.printError(Serial);
      }
    } else if (upload.status == UPLOAD_FILE_END) {
      if (Update.end(true)) {
        Serial.printf("[OTA] Success! Flashed %u bytes. Rebooting...\n", upload.totalSize);
      } else {
        Update.printError(Serial);
      }
    }
  });

  server.begin();
  Serial.println("[WiFi] Web server & Wireless OTA started on port 80.");
}

// ==============================================================================
// [7] MAIN RUNTIME LOOP
// ==============================================================================
void loop() {
  // Process incoming HTTP requests
  server.handleClient();
  
  // Feed the watchdog
  yield();

  bool hasPayload = false;

  // Allow manual payload injection via serial monitor
  if (Serial.available() > 0) {
    String manual = Serial.readStringUntil('\n');
    manual.trim();
    manual.toCharArray(payload, sizeof(payload));
    packetSequence++;
    hasPayload = true;
  } 
  // Automatic telemetry broadcast every 1000ms
  else if (millis() - lastSendTime >= 1000) {
    lastSendTime = millis();
    packetSequence++;
    readBattery();

    // Simulated AC readings (replace with real ZMPT101B when available)
    float simV = 230.0 + random(-15, 16) / 10.0;
    float simF = 49.9 + random(0, 3) / 10.0;

    // Build payload using snprintf (zero heap allocation, no fragmentation)
    snprintf(payload, sizeof(payload),
      "V:%.1f,F:%.2f,B:%d,S:%d,PB:%d,SEQ:%lu",
      simV, simF, batteryPercent, cellSignalDbm, phoneBatteryPercent, packetSequence);
    hasPayload = true;
  }

  // Transmit
  if (hasPayload) {
    Serial.print("TX [");
    Serial.print(packetSequence);
    Serial.print("]: ");
    Serial.print(payload);
    
    int state = radio.transmit(payload);

    if (state == RADIOLIB_ERR_NONE) {
      Serial.println(" -> OK");
      lastSuccessfulTx = millis();
      consecutiveTxFails = 0;
    } else {
      Serial.print(" -> FAIL (Code: ");
      Serial.print(state);
      Serial.println(")");
      consecutiveTxFails++;
    }
  }

  // ---- Radio Watchdog ----
  // If too many consecutive failures or no successful TX in 10 seconds,
  // force a radio reset to recover from stuck states
  if (consecutiveTxFails >= MAX_TX_FAILS || 
      (lastSuccessfulTx > 0 && millis() - lastSuccessfulTx > TX_WATCHDOG_MS)) {
    reinitRadio();
    lastSuccessfulTx = millis(); // Reset watchdog timer after reinit
  }
}

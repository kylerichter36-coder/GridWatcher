/*
  GridWatcher: Base Station (Transmitter)
  Hardware: FireBeetle 2 ESP32-C6, SX1262 LoRa, MT3608 Step-up
  Description: Acts as the off-grid power and cellular monitoring hub. 
  It handles a dual-mode WiFi stack (AP + STA), hosts a webserver for a smartphone SMS gateway, 
  and transmits telemetry via LoRa.
*/

#include <SPI.h>
#include <RadioLib.h>
#include <WiFi.h>
#include <WebServer.h>

// ==============================================================================
// [1] HARDWARE & PIN DEFINITIONS
// ==============================================================================

// LoRa SPI & Control Pins (Mapped for the ESP32-C6 RISC-V Architecture)
#define LORA_CS   14
#define LORA_DIO1 4
#define LORA_RST  1
#define LORA_BUSY 5
// Note: RXEN/TXEN header pins are driven internally by the chip's own DIO2 
// on this module, avoiding the need for manual GPIO RF switching.

// Power Sensing
#define PIN_BAT 0   // A0 - Onboard FireBeetle 2 C6 battery-sense voltage divider

// ==============================================================================
// [2] NETWORK CONFIGURATION (DUAL MODE WIFI)
// ==============================================================================
// The ESP32 operates in AP+STA mode. 
// STA (Station) connects to the main home router.
// AP (Access Point) broadcasts its own network. During a grid failure, 
// the router dies, but the AP remains active on battery power for local devices.
const char* homeSSID = "YOUR_HOME_WIFI_NAME";      
const char* homePass = "YOUR_HOME_WIFI_PASSWORD";  
const char* apSSID   = "GridWatcher-Home";
const char* apPass   = "gridwatcher123";            // Minimum 8 characters for WPA2

WebServer server(80);

// ==============================================================================
// [3] GLOBALS & STATE
// ==============================================================================
SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);

// Telemetry State
int cellSignalDbm = -999;           // -999 indicates no reading received yet from the phone
unsigned long lastCellUpdate = 0;   // Timestamp of last cellular ping
unsigned long lastWifiCheck = 0;
unsigned long lastSendTime = 0;     // Timestamp for LoRa TX pacing
unsigned long packetSequence = 0;   // Rolling packet counter to detect dropped packets
int batteryPercent = 100;

// ==============================================================================
// [4] HARDWARE & SENSOR FUNCTIONS
// ==============================================================================

/**
 * Reads the internal LiPo battery voltage via the onboard divider.
 * Converts millivolts to a 0-100% scale based on standard 3.3V-4.2V LiPo curves.
 */
void readBattery() {
  int mv = analogReadMilliVolts(PIN_BAT);
  int batteryMilliVolts = mv * 2; // Voltage divider math
  float pct = (batteryMilliVolts - 3300) / (4200.0 - 3300.0) * 100.0;
  batteryPercent = constrain((int)pct, 0, 100);
}

// ==============================================================================
// [5] WEBSERVER & HTTP ENDPOINTS
// ==============================================================================

/**
 * HTTP POST /signal
 * The repurposed Android phone running Termux hits this endpoint to update 
 * the current cellular network strength. (e.g., curl -X POST http://<IP>/signal -d "value=-85")
 */
void handleSignal() {
  if (server.hasArg("value")) {
    cellSignalDbm = server.arg("value").toInt();
    lastCellUpdate = millis();
    Serial.print("[WiFi] Cell signal received: ");
    Serial.println(cellSignalDbm);
    server.send(200, "text/plain", "OK");
  } else {
    server.send(400, "text/plain", "missing value param");
  }
}

/**
 * HTTP GET /status
 * Provides a real-time JSON snapshot of the base station state. 
 * Essential for future expansion into remote dashboards or database logging.
 */
void handleStatus() {
  String json = "{";
  json += "\"cellSignalDbm\":" + String(cellSignalDbm) + ",";
  json += "\"batteryPercent\":" + String(batteryPercent) + ",";
  json += "\"packetSequence\":" + String(packetSequence) + ",";
  json += "\"staConnected\":" + String(WiFi.status() == WL_CONNECTED ? "true" : "false") + ",";
  json += "\"staIP\":\"" + WiFi.localIP().toString() + "\"";
  json += "}";
  server.send(200, "application/json", json);
}

// ==============================================================================
// [6] SYSTEM INITIALIZATION
// ==============================================================================
void setup() {
  Serial.begin(115200);
  
  // Give the native USB CDC port time to open and connect to the PC
  delay(2500); 

  Serial.println("\n[ESP32-C6] Booting GridWatcher Home Sender...");
  analogReadResolution(12);
  
  // Initialize Hardware SPI (SCK=23, MISO=21, MOSI=22)
  // Hard-wiring this bus prevents bit-banging conflicts
  SPI.begin(23, 21, 22);

  // Initialize the SX1262 Radio (RadioLib bypasses standard library RISC-V compiler issues)
  // Set TX Power to maximum +22 dBm (158 mW) for maximum RF reach and obstacle penetration
  Serial.print("[SX1262] Initializing Radio (868MHz, SF9, BW125, +22dBm Max Power) ... ");
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 22, 8, 1.6, false);
  
  if (state == RADIOLIB_ERR_NONE) {
    Serial.println("Success!");
    // Crucial: Instructs the SX1262 to drive its own RF switch via its internal DIO2 pin
    radio.setDio2AsRfSwitch(true);
  } else {
    Serial.print("Failed with code: ");
    Serial.println(state);
    Serial.println("Check SPI wiring and RISC-V pin configurations.");
    while (true); // Halt execution on catastrophic RF failure
  }
  
  Serial.println("Setup complete. Starting transmission loop...");

  // Initialize Dual-Mode WiFi Stack
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(apSSID, apPass);
  Serial.print("[WiFi] AP started. Connect phone to '");
  Serial.print(apSSID);
  Serial.print("' -> IP: ");
  Serial.println(WiFi.softAPIP());

  WiFi.begin(homeSSID, homePass); // Non-blocking, retries in background
  Serial.println("[WiFi] STA connecting to home WiFi in background...");

  // Bind and start the web server routes
  server.on("/signal", HTTP_POST, handleSignal);
  server.on("/status", HTTP_GET, handleStatus);
  server.begin();
  Serial.println("[WiFi] Web server started on port 80.");
}

// ==============================================================================
// [7] MAIN RUNTIME LOOP
// ==============================================================================
void loop() {
  // Process incoming HTTP requests from the SMS Gateway phone
  server.handleClient();

  String payload = "";

  // Allow manual payload injection via serial monitor for debugging
  if (Serial.available() > 0) {
    payload = Serial.readStringUntil('\n');
    payload.trim();
    packetSequence++;
  } 
  // Trigger automatic telemetry broadcast every 1000ms (1 Hz)
  else if (millis() - lastSendTime >= 1000) {
    lastSendTime = millis();
    packetSequence++;
    readBattery();

    // ---------------------------------------------------------
    // ZMPT101B Telemetry Simulation
    // ---------------------------------------------------------
    // The active ZMPT101B modules are currently back-ordered. 
    // This logic generates a realistic, floating AC voltage (~230V) 
    // and frequency (~50Hz) to test the radio throughput and UI logic.
    float simulatedACVoltage = 230.0 + random(-15, 16) / 10.0;
    float simulatedFrequency = 49.9 + random(0, 3) / 10.0;

    // Construct the comma-separated data packet
    payload = "V:" + String(simulatedACVoltage, 1) + 
              ",F:" + String(simulatedFrequency, 2) + 
              ",B:" + String(batteryPercent) +
              ",S:" + String(cellSignalDbm) +
              ",SEQ:" + String(packetSequence);
  }

  // Transmit the payload over the LoRa RF link
  if (payload.length() > 0) {
    Serial.print("TX [" + String(packetSequence) + "]: " + payload);
    
    // Transmit blocking - ensures clean RF state before continuing
    int state = radio.transmit(payload);

    if (state == RADIOLIB_ERR_NONE) {
      Serial.println(" -> OK");
    } else {
      Serial.println(" -> FAIL (Code: " + String(state) + ")");
    }
  }
}

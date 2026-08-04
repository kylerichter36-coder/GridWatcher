/*
  GRIDWATCHR Handheld Dashboard v3 — Legal + Optimized
  FireBeetle 2 ESP32-C6 + 76x284 long-strip ST7789 TFT (portrait)

  Fixes in v3:
  - IRAM_ATTR ISR (was ICACHE_RAM_ATTR — ESP8266 only, broken on RISC-V)
  - drawWallpaper() uses memcpy instead of 21,584 drawPixel() calls (10-50x faster)
  - WiFi/OTA is OFF by default — activate with long BOOT button press (saves ~80mA)
  - Battery read throttled to every 30 seconds (was every second)
  - SLEEP_MS reduced to 2 minutes (was 5)
  - LINK_TIMEOUT_MS increased to 5000ms (fewer false OFFLINE flashes)
  - Packet loss counters reset on link reconnect
  - linkQual uses weighted RSSI + SNR (was SNR-only)
  - SNR displayed in WIRELESS section
  - Cell signal not shown when stale (was shown forever)

  LoRa Packet Format (v2):
  V:<voltage>,F:<freq>,B:<base_batt>,S:<cell_dbm>,PB:<phone_batt>,SEQ:<seq>
*/

#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <RadioLib.h>
#include <WiFi.h>
#include <WebServer.h>
#include <Update.h>
#include <ESPmDNS.h>
#include <HTTPClient.h>
#include "wallpaper.h"

// WiFi OTA — connects to sender AP and pulls firmware from sender hub
const char* otaSSID = "GridWatcher-Home";  // sender AP
const char* otaPass = "gridwatcher123";
#define SENDER_HOST "http://192.168.4.1"
WebServer otaServer(80);
bool otaModeActive = false;

const char* otaHTML =
"<!DOCTYPE html><html><head><title>GridWatcher Dashboard OTA</title>"
"<style>body{font-family:sans-serif;background:#121212;color:#fff;text-align:center;padding-top:50px;}"
"input[type=file]{margin:20px 0;padding:10px;background:#222;color:#fff;border:1px solid #444;border-radius:5px;}"
"input[type=submit]{padding:10px 20px;background:#00e676;color:#000;border:none;font-weight:bold;border-radius:5px;cursor:pointer;}"
"</style></head><body><h2>GridWatcher Dashboard Firmware OTA</h2>"
"<form method='POST' action='/update' enctype='multipart/form-data'>"
"<input type='file' name='update'><br><br>"
"<input type='submit' value='Flash Dashboard Wireless'>"
"</form></body></html>";

// ---------- Pins ----------
#define PIN_SCL   23
#define PIN_SDA   22
#define PIN_RES   2
#define PIN_DC    20
#define PIN_CS    19
#define PIN_BLK   18
#define PIN_BAT   0
#define PIN_BOOT_BTN 9

// ---------- LoRa Pins ----------
#define LORA_CS   14
#define LORA_DIO1 4
#define LORA_RST  1
#define LORA_BUSY 5

// LoRa radio config — MUST match exactly on sender and handheld
#define LORA_FREQ   868.0
#define LORA_BW     125.0
#define LORA_SF     10      // Spreading Factor (7-12). Higher = longer range, slower
#define LORA_CR     7       // Coding Rate (5-8)
#define LORA_SYNC   0x12    // Sync word — private network
#define LORA_PREAMBLE 8

// Onboard LED for visual RX feedback
#ifndef LED_BUILTIN
  #define LED_BUILTIN 8
#endif
#define LED_PIN    LED_BUILTIN
#define LED_RX_MS  50
#define LED_ERR_MS 200
unsigned long ledOffMs = 0;

Adafruit_ST7789 tft = Adafruit_ST7789(&SPI, PIN_CS, PIN_DC, PIN_RES);
SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);

#define SCR_W 76
#define SCR_H 284
GFXcanvas16 canvas(SCR_W, SCR_H);

// ---------- Theme Palettes ----------
struct Theme {
  uint16_t text; uint16_t dim; uint16_t line; uint16_t accent; uint16_t white;
};
const Theme THEME_DARK  = { 0xCE79, 0x738E, 0x39C7, 0x4D3F, 0xFFFF };
const Theme THEME_LIGHT = { 0x2124, 0x4A69, 0x9CD3, 0x11B5, 0x0000 };

#define COL_GOOD 0x2E8B
#define COL_WARN 0xFD20
#define COL_CRIT 0xF800
#define ENABLE_THEME_TOGGLE 1

bool darkMode = true;
Theme cur = THEME_DARK;

// ---------- Live Data Variables ----------
float voltage   = 0.0;
float freq_Hz   = 0.0;
int   rssi_dBm  = 0;
float snr_dB    = 0.0;
int   linkQual  = 0;
float pktLoss   = 0.0;

// AI Prediction
int   aiRisk = 0;
const char* aiState = "WAIT";

int batteryPercent     = 0;
int batteryMilliVolts  = 0;
bool isCharging        = false;
unsigned long lastBattRead = 0;
#define BATT_READ_MS  30000  // Read battery every 30s (was every second)
#define BATT_GOOD_PCT 60
#define BATT_WARN_PCT 30

int homeBatteryPercent  = -1;
int phoneBatteryPercent = -1;
int cellSignalDbm       = -999;

// Link freshness
unsigned long lastPacketMillis = 0;
bool linkAlive = false;
#define LINK_TIMEOUT_MS 5000  // 5s (was 3s) — fewer false OFFLINE flashes

// Screen sleep
bool screenAwake       = true;
unsigned long lastActivity = 0;
const unsigned long SLEEP_MS = 2UL * 60UL * 1000UL;  // 2 min (was 5 min)

// Button long-press for OTA mode
#define OTA_LONG_PRESS_MS 3000
unsigned long btnPressStart = 0;
bool btnHeld = false;

// Voltage history graph
#define HIST_LEN 40
float vHist[HIST_LEN];
int histIdx = 0;

// AI: rolling voltage/freq history for anomaly detection
#define AI_HIST_LEN 10
float aiVoltHist[AI_HIST_LEN];
float aiFreqHist[AI_HIST_LEN];
int aiHistIdx = 0;

// Stats ticker — runs every 1s independent of display
unsigned long lastUpdate = 0;
const unsigned long UPDATE_MS = 1000;
bool btnLastRaw = HIGH;
unsigned long btnLastChange = 0;
const unsigned long DEBOUNCE_MS = 40;

// Data-triggered display — draw 50ms AFTER new data arrives, not on a fixed clock
volatile bool newDataFlag = false;
unsigned long dataReceivedMs = 0;
#define DRAW_DELAY_MS 50

// LoRa tracking stats
unsigned long lastExpectedSeq       = 0;
int packetsReceivedThisSecond       = 0;
float rxRate                        = 0.0;
long totalLostPackets               = 0;
long totalExpectedPackets           = 0;

// RX Watchdog — if no packet (or no flag set) for this long, force re-arm
#define RX_WATCHDOG_MS 15000
unsigned long lastRxArmTime = 0;

// ---------- Interrupt-driven receive flag ----------
volatile bool receivedFlag = false;

// FIXED: IRAM_ATTR (not ICACHE_RAM_ATTR which is ESP8266-only)
// IRAM_ATTR ensures the ISR runs from fast internal RAM on ESP32-C6 RISC-V
IRAM_ATTR void onPacketReceived(void) {
  receivedFlag = true;
}

// ==============================================================================
// Shared helper to check for updates from the sender hub.
// If bootCheck is true, it fails silently and quickly (3s timeout) so normal boot is fast.
// If bootCheck is false, it prints errors on screen and waits up to 10s to connect.
bool checkForUpdates(bool bootCheck) {
  unsigned long timeout = bootCheck ? 3000 : 10000;
  Serial.println(bootCheck ? "[OTA] Boot update check starting..." : "[OTA] Manual update check starting...");

  // Show connecting screen
  canvas.fillScreen(0x0000);
  canvas.setTextColor(0xFFFF);
  canvas.setTextSize(1);
  canvas.setCursor(2, 50);
  canvas.print("OTA CHECK");
  canvas.setCursor(2, 66);
  canvas.setTextColor(0x4D3F);
  canvas.print(bootCheck ? "Auto-checking..." : "Connecting...");
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
  digitalWrite(PIN_BLK, HIGH);

  WiFi.mode(WIFI_STA);
  WiFi.begin(otaSSID, otaPass);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeout) delay(100);

  if (WiFi.status() != WL_CONNECTED) {
    WiFi.disconnect();
    WiFi.mode(WIFI_OFF);
    if (!bootCheck) {
      canvas.fillScreen(0x0000);
      canvas.setTextColor(0xF800);
      canvas.setCursor(2, 60); canvas.print("SENDER AP");
      canvas.setCursor(2, 74); canvas.print("NOT FOUND");
      canvas.setCursor(2, 95); canvas.setTextColor(0x738E);
      canvas.print("Is sender on?");
      tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
      delay(2000);
    }
    Serial.println("[OTA] Could not connect to sender AP");
    return false;
  }
  Serial.printf("[OTA] Connected to sender AP -> %s\n", WiFi.localIP().toString().c_str());

  // Check if update is available
  HTTPClient http;
  http.begin(String(SENDER_HOST) + "/handheld-update-available");
  int code = http.GET();
  String available = (code == HTTP_CODE_OK) ? http.getString() : "no";
  http.end();

  if (available != "yes") {
    WiFi.disconnect();
    WiFi.mode(WIFI_OFF);
    if (!bootCheck) {
      canvas.fillScreen(0x0000);
      canvas.setTextColor(0x07E0);
      canvas.setCursor(2, 55); canvas.print("UP TO DATE");
      canvas.setCursor(2, 72); canvas.setTextColor(0x738E);
      canvas.print("No update on");
      canvas.setCursor(2, 85); canvas.print("sender hub");
      tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
      delay(1500);
    }
    Serial.println("[OTA] No update available on sender");
    return false;
  }

  // Update available — stream from sender
  Serial.println("[OTA] Update available! Downloading from sender...");
  canvas.fillScreen(0x0000);
  canvas.setTextColor(0xFFFF);
  canvas.setCursor(2, 45); canvas.print("UPDATING");
  canvas.setCursor(2, 60); canvas.setTextColor(0x4D3F);
  canvas.print("Downloading...");
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);

  HTTPClient dlHttp;
  dlHttp.begin(String(SENDER_HOST) + "/handheld-firmware");
  int dlCode = dlHttp.GET();

  if (dlCode == HTTP_CODE_OK) {
    int contentLen = dlHttp.getSize();
    bool canBegin  = Update.begin(contentLen > 0 ? contentLen : UPDATE_SIZE_UNKNOWN);
    if (canBegin) {
      WiFiClient* stream = dlHttp.getStreamPtr();
      size_t written = Update.writeStream(*stream);
      if (Update.end()) {
        Serial.printf("[OTA] Success! %u bytes written\n", written);
        // Confirm to sender hub
        HTTPClient conf;
        conf.begin(String(SENDER_HOST) + "/device-updated?device=handheld");
        conf.POST("");
        conf.end();
        // Show success then reboot
        canvas.fillScreen(0x0000);
        canvas.setTextColor(0x07E0);
        canvas.setCursor(2, 50); canvas.print("UPDATED!");
        canvas.setCursor(2, 65); canvas.setTextColor(0xFFFF);
        canvas.print("Rebooting...");
        tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
        delay(1500);
        ESP.restart();
      } else {
        Update.printError(Serial);
      }
    } else {
      Serial.println("[OTA] Update.begin() failed — not enough space?");
    }
  } else {
    Serial.printf("[OTA] Download failed, HTTP %d\n", dlCode);
  }
  dlHttp.end();

  WiFi.disconnect();
  WiFi.mode(WIFI_OFF);

  canvas.fillScreen(0x0000);
  canvas.setTextColor(0xF800);
  canvas.setCursor(2, 60); canvas.print("OTA FAIL");
  canvas.setCursor(2, 75); canvas.setTextColor(0x738E);
  canvas.print("Check serial");
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
  delay(2000);
  return false;
}

// OTA mode: connect to sender AP, pull firmware from sender hub manually
void startOTAMode() {
  if (otaModeActive) return;
  otaModeActive = true;
  checkForUpdates(false); // manual check
  otaModeActive = false;
}

// ==============================================================================
// BUTTON HANDLER
// ==============================================================================
void pollBootButton() {
  bool raw = digitalRead(PIN_BOOT_BTN);

  if (raw != btnLastRaw) {
    btnLastChange = millis();
    btnLastRaw    = raw;
  }

  static bool armed = true;

  if (millis() - btnLastChange > DEBOUNCE_MS) {
    if (raw == LOW) {
      if (armed) {
        // Track how long it's been held
        if (btnPressStart == 0) btnPressStart = millis();

        // Long press: 3 seconds → OTA mode
        if (!otaModeActive && millis() - btnPressStart >= OTA_LONG_PRESS_MS) {
          startOTAMode();
          armed = false;
        }
      }
    } else {
      // Button released
      if (btnPressStart > 0 && millis() - btnPressStart < OTA_LONG_PRESS_MS) {
        // Short press: wake screen / toggle theme
        if (!screenAwake) {
          screenAwake = true;
          digitalWrite(PIN_BLK, HIGH);
          lastActivity = millis();
          drawFrame();
        } else {
          lastActivity = millis();
#if ENABLE_THEME_TOGGLE
          darkMode = !darkMode;
          cur = darkMode ? THEME_DARK : THEME_LIGHT;
          drawFrame();
#endif
        }
      }
      btnPressStart = 0;
      armed = true;
    }
  }
}

// ==============================================================================
// BATTERY READ — throttled to every 30 seconds
// ==============================================================================
void readBattery() {
  unsigned long now = millis();
  if (lastBattRead > 0 && now - lastBattRead < BATT_READ_MS) return;
  lastBattRead = now;

  long sum = 0;
  for (int i = 0; i < 20; i++) {
    sum += analogReadMilliVolts(PIN_BAT);
    delayMicroseconds(250);
  }
  int rawMv = (sum / 20) * 2;

  static float smoothedMv = 0;
  if (smoothedMv == 0) smoothedMv = rawMv;
  else smoothedMv = (smoothedMv * 0.85) + (rawMv * 0.15);

  batteryMilliVolts = (int)smoothedMv;
  float pct = ((float)batteryMilliVolts - 3300.0) / (4200.0 - 3300.0) * 100.0;
  batteryPercent = constrain((int)pct, 0, 100);

  static int vHistory[10] = {0};
  static int historyIdx   = 0;
  static unsigned long lastHistTime = 0;
  if (millis() - lastHistTime >= 30000 || lastHistTime == 0) {
    lastHistTime = millis();
    vHistory[historyIdx] = batteryMilliVolts;
    historyIdx = (historyIdx + 1) % 10;
  }

  int oldestSample = vHistory[historyIdx];
  int trendDelta   = (oldestSample > 0) ? (batteryMilliVolts - oldestSample) : 0;

  // Wider charging threshold — ±25mV to reduce false toggling
  if      (trendDelta >= 25 || (batteryMilliVolts >= 4150 && trendDelta >= -5))
    isCharging = true;
  else if (trendDelta <= -10 && batteryMilliVolts < 4120)
    isCharging = false;
}

// ==============================================================================
// AI RISK CALCULATION
// ==============================================================================
void updateAIRisk() {
  float vRisk = 0.0, fRisk = 0.0, cRisk = 0.0;

  float vDev = abs(voltage - 230.0);
  if      (vDev > 20.0) vRisk = 100.0;
  else if (vDev > 10.0) vRisk = map(vDev * 10, 100, 200, 30, 80);
  else if (vDev > 5.0)  vRisk = map(vDev * 10, 50, 100, 10, 30);

  float fDev = abs(freq_Hz - 50.0);
  if      (fDev > 2.0) fRisk = 100.0;
  else if (fDev > 0.5) fRisk = map(fDev * 100, 50, 200, 20, 80);

  if      (cellSignalDbm == -999) cRisk = 10.0;
  else if (cellSignalDbm < -110)  cRisk = 40.0;
  else if (cellSignalDbm < -100)  cRisk = 15.0;

  float totalRisk = (vRisk * 0.45) + (fRisk * 0.40) + (cRisk * 0.15);
  aiRisk = constrain((int)totalRisk, 0, 100);

  if      (!linkAlive)     aiState = "NO LINK";
  else if (aiRisk >= 60)   aiState = "OUTAGE";
  else if (aiRisk >= 25)   aiState = "WARNING";
  else                     aiState = "STABLE";
}

// ==============================================================================
// DRAWING HELPERS
// ==============================================================================
void drawBatteryIcon(int x, int y, int percent, bool charging) {
  uint16_t col = (percent >= BATT_GOOD_PCT) ? COL_GOOD
               : (percent >= BATT_WARN_PCT) ? COL_WARN : COL_CRIT;
  canvas.drawRect(x, y, 16, 8, col);
  canvas.drawFastVLine(x + 16, y + 2, 4, col);
  canvas.fillRect(x + 1, y + 1, (14 * percent) / 100, 6, col);
  if (charging) {
    canvas.drawLine(x + 9, y - 1, x + 5, y + 4, cur.white);
    canvas.drawLine(x + 5, y + 4, x + 8, y + 4, cur.white);
    canvas.drawLine(x + 8, y + 4, x + 4, y + 9, cur.white);
  }
}

void drawBatteryRow(int x, int y, int percent, bool charging, const char* label) {
  uint16_t col = (percent >= BATT_GOOD_PCT) ? COL_GOOD
               : (percent >= BATT_WARN_PCT) ? COL_WARN : COL_CRIT;
  if (percent < 0) {
    canvas.setTextColor(cur.dim);
    canvas.setCursor(x, y);
    canvas.printf("%s --", label);
    return;
  }
  canvas.drawRect(x, y, 14, 7, col);
  canvas.drawFastVLine(x + 14, y + 2, 3, col);
  canvas.fillRect(x + 1, y + 1, (12 * percent) / 100, 5, col);
  if (charging) {
    canvas.drawLine(x + 8, y - 1, x + 5, y + 3, cur.white);
    canvas.drawLine(x + 5, y + 3, x + 7, y + 3, cur.white);
    canvas.drawLine(x + 7, y + 3, x + 4, y + 8, cur.white);
  }
  canvas.setTextColor(cur.text);
  canvas.setCursor(x + 18, y);
  canvas.printf("%d%%", percent);
  canvas.setTextColor(cur.dim);
  canvas.setCursor(x + 46, y);
  canvas.print(label);
}

// FIXED: Use memcpy instead of 21,584 drawPixel() calls (10-50x faster)
void drawWallpaper() {
  const uint16_t* src = darkMode ? wallpaper_dark : wallpaper_light;
  memcpy(canvas.getBuffer(), src, SCR_W * SCR_H * 2);
}

// ==============================================================================
// MAIN FRAME DRAW
// ==============================================================================
void drawFrame() {
  drawWallpaper();
  canvas.setTextWrap(false);
  int y = 0;

  // TITLE BAR
  canvas.setTextSize(1);
  canvas.setTextColor(cur.white);
  canvas.setCursor(2, 2);
  canvas.print("GRIDWATCHR");
  canvas.drawFastHLine(0, 11, SCR_W, cur.line);

  // SECTION 1: WIRELESS
  y = 14;
  canvas.setTextColor(cur.accent);
  canvas.setCursor(2, y);
  canvas.print("WIRELESS");
  canvas.drawFastHLine(0, y + 9, SCR_W, cur.line);

  y += 12;
  canvas.setTextColor(cur.dim); canvas.setCursor(2, y);  canvas.print("LORA");
  canvas.setTextColor(cur.text); canvas.setCursor(28, y);
  if (linkAlive) canvas.printf("%ddBm", rssi_dBm);
  else           canvas.print("--");

  y += 9;
  canvas.setTextColor(cur.dim); canvas.setCursor(2, y);  canvas.print("SNR");
  canvas.setTextColor(cur.text); canvas.setCursor(28, y);
  if (linkAlive) canvas.printf("%.1fdB", snr_dB);
  else           canvas.print("--");

  y += 9;
  canvas.setTextColor(cur.dim); canvas.setCursor(2, y);  canvas.print("QUAL");
  canvas.setTextColor(cur.text); canvas.setCursor(28, y);
  if (linkAlive) canvas.printf("%d%%", linkQual);
  else           canvas.print("--");

  y += 9;
  canvas.setTextColor(cur.dim); canvas.setCursor(2, y);  canvas.print("CELL");
  canvas.setTextColor(cur.text); canvas.setCursor(28, y);
  if (cellSignalDbm != -999 && linkAlive) canvas.printf("%ddBm", cellSignalDbm);
  else                                    canvas.print("--");

  y += 9;
  canvas.setTextColor(cur.dim); canvas.setCursor(2, y);  canvas.print("LOSS");
  canvas.setTextColor(cur.text); canvas.setCursor(28, y);
  canvas.printf("%.1f%%", pktLoss);

  y += 10;
  canvas.drawFastHLine(0, y, SCR_W, cur.line);

  // SECTION 2: READINGS
  y += 3;
  canvas.setTextColor(cur.accent); canvas.setCursor(2, y);
  canvas.print("READINGS");
  canvas.drawFastHLine(0, y + 9, SCR_W, cur.line);

  y += 12;
  canvas.setTextSize(2);
  canvas.setTextColor(cur.white);
  canvas.setCursor(2, y);
  canvas.printf("%.1fV", voltage);
  canvas.setTextSize(1);

  y += 18;
  canvas.setTextColor(cur.text);
  canvas.setCursor(2, y);
  canvas.printf("%.2f Hz", freq_Hz);

  y += 12;
  canvas.setTextColor(cur.dim); canvas.setCursor(2, y);
  canvas.print("V TREND");

  int gx0 = 3, gy0 = y + 9, gw = SCR_W - 6, gh = 36;
  canvas.drawRect(gx0 - 1, gy0 - 1, gw + 2, gh + 2, cur.line);

  float vmin = vHist[0], vmax = vHist[0];
  for (int i = 0; i < HIST_LEN; i++) {
    if (vHist[i] < vmin) vmin = vHist[i];
    if (vHist[i] > vmax) vmax = vHist[i];
  }
  if (vmax - vmin < 1.0) { vmax += 0.5; vmin -= 0.5; }

  int prevX = -1, prevY = 0;
  for (int i = 0; i < HIST_LEN; i++) {
    int idx = (histIdx + i) % HIST_LEN;
    int x   = gx0 + (i * gw) / (HIST_LEN - 1);
    int py  = gy0 + gh - (int)(((vHist[idx] - vmin) / (vmax - vmin)) * gh);
    py = constrain(py, gy0, gy0 + gh - 1);
    if (prevX >= 0) canvas.drawLine(prevX, prevY, x, py, cur.accent);
    prevX = x; prevY = py;
  }

  y = gy0 + gh + 4;
  canvas.drawFastHLine(0, y, SCR_W, cur.line);

  // SECTION 3: BATTERIES
  y += 3;
  canvas.setTextColor(cur.accent); canvas.setCursor(2, y);
  canvas.print("BATTERIES");
  canvas.drawFastHLine(0, y + 9, SCR_W, cur.line);

  y += 12; drawBatteryRow(2, y, batteryPercent,     isCharging, "HND");
  y += 10; drawBatteryRow(2, y, homeBatteryPercent, false,      "HME");
  y += 10; drawBatteryRow(2, y, phoneBatteryPercent,false,      "PHN");

  y += 11;
  canvas.drawFastHLine(0, y, SCR_W, cur.line);

  // SECTION 4: AI PREDICT
  y += 3;
  canvas.setTextColor(cur.accent); canvas.setCursor(2, y);
  canvas.print("AI PREDICT");
  canvas.drawFastHLine(0, y + 9, SCR_W, cur.line);

  y += 12;
  uint16_t stateCol = (aiRisk >= 60) ? COL_CRIT : (aiRisk >= 25) ? COL_WARN : COL_GOOD;
  canvas.setTextColor(stateCol); canvas.setCursor(2, y);  canvas.print(aiState);
  canvas.setTextColor(cur.text); canvas.setCursor(50, y); canvas.printf("%d%%", aiRisk);

  y += 10;
  int bx = 2, bw = SCR_W - 4, bh = 6;
  canvas.drawRect(bx, y, bw, bh, cur.line);
  uint16_t barCol = (aiRisk >= 60) ? COL_CRIT : (aiRisk >= 25) ? COL_WARN : COL_GOOD;
  canvas.fillRect(bx + 1, y + 1, ((bw - 2) * aiRisk) / 100, bh - 2, barCol);

  y += bh + 4;
  canvas.drawFastHLine(0, y, SCR_W, cur.line);

  // FOOTER: Status + uptime
  y += 3;
  canvas.setCursor(2, y);
  if (lastPacketMillis == 0) {
    canvas.setTextColor(cur.dim); canvas.print("NO DATA YET");
  } else if (!linkAlive) {
    canvas.setTextColor(COL_CRIT);
    canvas.printf("OFFLINE %lus", (millis() - lastPacketMillis) / 1000);
  } else {
    canvas.setTextColor(COL_GOOD); canvas.print("LIVE");
    canvas.setTextColor(cur.dim);  canvas.printf(" %.0fpps", rxRate);
  }

  y += 10;
  unsigned long upSecs = millis() / 1000UL;
  canvas.setTextColor(cur.dim); canvas.setCursor(2, y);
  canvas.printf("UP %02lu:%02lu:%02lu",
                upSecs / 3600UL,
                (upSecs % 3600UL) / 60UL,
                upSecs % 60UL);

  // OTA mode indicator
  if (otaModeActive) {
    canvas.setTextColor(COL_WARN);
    canvas.setCursor(48, y);
    canvas.print("OTA ON");
  }

  // No interrupt guard needed here — the 50ms DRAW_DELAY_MS ensures the radio
  // has been in idle RX for at least 50ms before we touch the SPI bus.
  // SF10 airtime = 410ms, TX interval = 2s, so the bus is always free at draw time.
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
}


// ==============================================================================
// SETUP
// ==============================================================================
void setup() {
  Serial.begin(115200);
  delay(500);
  Serial.println("\n[Handheld] Booting GridWatchr Dashboard v3...");

  pinMode(PIN_BLK, OUTPUT);
  digitalWrite(PIN_BLK, HIGH);
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);
  analogReadResolution(12);

  SPI.begin(23, 21, 22);

  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  tft.init(76, 284);
  tft.setRotation(2);
  tft.invertDisplay(false);
  tft.fillScreen(ST77XX_BLACK);

  // Check for auto-update on boot.
  // Silently exits in 3s if sender AP not found, preserving fast boot.
  checkForUpdates(true);

  // Hard reset the radio before init — clears any stuck state from previous flash
  pinMode(LORA_RST, OUTPUT);
  digitalWrite(LORA_RST, LOW);
  delay(20);
  digitalWrite(LORA_RST, HIGH);
  delay(100); // Let SX1262 fully settle after reset

  int state = radio.begin(LORA_FREQ, LORA_BW, LORA_SF, LORA_CR,
                          LORA_SYNC, 10, LORA_PREAMBLE, 1.6, false);
  if (state == RADIOLIB_ERR_NONE) {
    // setDio2AsRfSwitch(false) = no external RF switch controlled by DIO2
    // Many SX1262 breakout modules have no external switch; enabling DIO2 RF control
    // can block the RX path. Try false first — change to true only if TX also breaks.
    radio.setDio2AsRfSwitch(false);
    radio.setPacketReceivedAction(onPacketReceived);
    delay(50);
    int startState = radio.startReceive();
    if (startState != RADIOLIB_ERR_NONE) {
      Serial.printf("[LoRa] startReceive FAILED during init, code: %d\n", startState);
    }
    // Read DIO1 immediately — should be LOW (waiting for packet), never HIGH straight after arm
    Serial.printf("[LoRa] DIO1 state after startReceive: %d (expect 0)\n",
                  digitalRead(LORA_DIO1));
    lastRxArmTime = millis();
    Serial.println("[LoRa] Initialized and listening.");
    Serial.println("============================================================");
    Serial.printf("  HANDHELD RADIO CONFIG\n");
    Serial.printf("  Freq:     %.1f MHz\n",   LORA_FREQ);
    Serial.printf("  SF:       %d\n",          LORA_SF);
    Serial.printf("  BW:       %.0f kHz\n",   LORA_BW);
    Serial.printf("  CR:       4/%d\n",        LORA_CR);
    Serial.printf("  SyncWord: 0x%02X\n",      LORA_SYNC);
    Serial.printf("  Preamble: %d\n",          LORA_PREAMBLE);
    Serial.println("  >>> SENDER MUST MATCH ALL VALUES ABOVE <<<");
    Serial.println("============================================================");
  } else {
    Serial.printf("[LoRa] Init FAILED, code: %d\n", state);
  }

  // WiFi is OFF at boot — saves ~80mA constantly
  // To enable OTA: hold BOOT button for 3 seconds
  WiFi.mode(WIFI_OFF);
  Serial.println("[WiFi] Off by default. Hold BOOT 3s to activate OTA mode.");

  for (int i = 0; i < HIST_LEN; i++) vHist[i] = 0.0;
  for (int i = 0; i < AI_HIST_LEN; i++) { aiVoltHist[i] = 230.0; aiFreqHist[i] = 50.0; }

  readBattery();
  lastActivity = millis();
  drawFrame();
}

// ==============================================================================
// MAIN LOOP
// ==============================================================================

// Non-blocking LED tick
inline void ledTick() {
  if (ledOffMs > 0 && millis() >= ledOffMs) {
    digitalWrite(LED_PIN, LOW);
    ledOffMs = 0;
  }
}

void loop() {
  if (otaModeActive) otaServer.handleClient();
  pollBootButton();
  ledTick();

  // DIO1 POLLING FALLBACK — ESP32-C6 GPIO interrupts can silently fail to fire.
  // The SX1262 holds DIO1 HIGH until the FIFO is read, so polling catches it.
  // This runs every loop iteration (~microseconds) so latency is negligible.
  if (!receivedFlag && digitalRead(LORA_DIO1) == HIGH) {
    Serial.println("[LoRa] POLL caught DIO1 HIGH (ISR missed — interrupt may not be firing)");
    receivedFlag = true;
  }

  // RX Watchdog — also re-attaches the interrupt on every re-arm as a recovery attempt
  if (millis() - lastRxArmTime > RX_WATCHDOG_MS && !receivedFlag) {
    Serial.printf("[LoRa] RX watchdog: DIO1=%d, re-arming... ",
                  digitalRead(LORA_DIO1));
    radio.setPacketReceivedAction(onPacketReceived);
    int startState = radio.startReceive();
    Serial.printf("result: %d  DIO1 after: %d\n",
                  startState, digitalRead(LORA_DIO1));
    lastRxArmTime = millis();
    digitalWrite(LED_PIN, HIGH);
    ledOffMs = millis() + LED_ERR_MS;
  }

  if (receivedFlag) {
    receivedFlag  = false;
    lastRxArmTime = millis();

    // Read RSSI/SNR BEFORE readData — these are valid as soon as the IRQ fires
    float irqRSSI = radio.getRSSI();
    float irqSNR  = radio.getSNR();
    Serial.printf("[LoRa] IRQ fired — RSSI: %.0fdBm  SNR: %.1fdB\n",
                  irqRSSI, irqSNR);

    String str;
    int state = radio.readData(str);

    int startState = radio.startReceive();
    if (startState != RADIOLIB_ERR_NONE) {
      Serial.printf("[LoRa] startReceive FAILED after read, code: %d\n", startState);
    }
    lastRxArmTime = millis();

    if (state == RADIOLIB_ERR_NONE) {
      str.trim();
      Serial.printf("[LoRa] readData OK  raw: \"%s\"\n", str.c_str());
      digitalWrite(LED_PIN, HIGH);
      ledOffMs = millis() + LED_RX_MS;
    } else {
      Serial.printf("[LoRa] readData FAIL code %d ", state);
      if      (state == -2) Serial.println("(CRC error — likely SF/BW/sync mismatch with sender)");
      else if (state == -3) Serial.println("(Header error — preamble detected but header corrupt)");
      else                  Serial.printf ("(unknown error)\n");
    }

    if (state == RADIOLIB_ERR_NONE) {

      int vIdx   = str.indexOf("V:");
      int fIdx   = str.indexOf(",F:");
      int bIdx   = str.indexOf(",B:");
      int cellIdx= str.indexOf(",S:");
      int pbIdx  = str.indexOf(",PB:");
      int sIdx   = str.indexOf(",SEQ:");

      if (vIdx >= 0 && fIdx > vIdx && sIdx > fIdx) {
        packetsReceivedThisSecond++;
        lastPacketMillis = millis();

        voltage  = str.substring(vIdx + 2, fIdx).toFloat();
        freq_Hz  = str.substring(fIdx + 3, (bIdx > fIdx ? bIdx : sIdx)).toFloat();

        if (bIdx > fIdx) {
          int bEnd = (cellIdx > bIdx) ? cellIdx : sIdx;
          homeBatteryPercent = str.substring(bIdx + 3, bEnd).toInt();
        }
        if (cellIdx > fIdx) {
          int sEnd = (pbIdx > cellIdx) ? pbIdx : sIdx;
          cellSignalDbm = str.substring(cellIdx + 3, sEnd).toInt();
        }
        if (pbIdx > 0 && sIdx > pbIdx) {
          phoneBatteryPercent = str.substring(pbIdx + 4, sIdx).toInt();
        }

        unsigned long seq = str.substring(sIdx + 5).toInt();
        if (lastExpectedSeq != 0 && seq > lastExpectedSeq) {
          totalLostPackets += (seq - lastExpectedSeq);
        }
        totalExpectedPackets++;
        lastExpectedSeq = seq + 1;

        if (totalExpectedPackets > 0) {
          pktLoss = ((float)totalLostPackets /
                     (float)(totalExpectedPackets + totalLostPackets)) * 100.0;
        }

        rssi_dBm = (int)radio.getRSSI();
        snr_dB   = radio.getSNR();

        int rssiScore = constrain(map(rssi_dBm, -130, -60, 0, 100), 0, 100);
        int snrScore  = constrain(map((int)snr_dB, -20, 10, 0, 100), 0, 100);
        linkQual = (rssiScore * 60 + snrScore * 40) / 100;

        histIdx = (histIdx + 1) % HIST_LEN;
        vHist[histIdx] = voltage;
        aiVoltHist[aiHistIdx] = voltage;
        aiFreqHist[aiHistIdx] = freq_Hz;
        aiHistIdx = (aiHistIdx + 1) % AI_HIST_LEN;

        // Signal that fresh data is ready — display will draw after DRAW_DELAY_MS
        newDataFlag   = true;
        dataReceivedMs = millis();
      }
    } // end state == RADIOLIB_ERR_NONE (parse block)
  } // end receivedFlag

  // Auto-sleep
  if (screenAwake && (millis() - lastActivity > SLEEP_MS)) {
    screenAwake = false;
    digitalWrite(PIN_BLK, LOW);
  }

  // ---- 1s Stats Ticker (runs independently of display) ----
  if (millis() - lastUpdate >= UPDATE_MS) {
    lastUpdate = millis();

    rxRate = packetsReceivedThisSecond;
    packetsReceivedThisSecond = 0;

    bool wasAlive = linkAlive;
    linkAlive = (lastPacketMillis != 0) && (millis() - lastPacketMillis < LINK_TIMEOUT_MS);
    if (!linkAlive) linkQual = 0;

    if (!wasAlive && linkAlive) {
      totalLostPackets     = 0;
      totalExpectedPackets = 0;
      pktLoss              = 0.0;
      lastExpectedSeq      = 0;
      Serial.println("[LoRa] Link reconnected — loss counters reset.");
    }

    // Wake + force redraw on link state change (OFFLINE / LIVE flip)
    if (wasAlive != linkAlive) {
      screenAwake    = true;
      lastActivity   = millis();
      newDataFlag    = true;
      dataReceivedMs = millis();
      digitalWrite(PIN_BLK, HIGH);
    }

    updateAIRisk();
    readBattery();
  }

  // ---- Data-triggered display: draw exactly 50ms after new data arrives ----
  // The 50ms gap guarantees the SX1262 is idle in RX before we take the SPI bus.
  // SF10 airtime ~410ms + 2s TX interval = next packet can't arrive for ~1.6s after draw.
  if (newDataFlag && screenAwake &&
      (millis() - dataReceivedMs >= DRAW_DELAY_MS)) {
    // Don't draw if another packet just arrived — process it first next iteration
    if (!receivedFlag) {
      newDataFlag = false;
      drawFrame();
      // Safety re-arm: catches any DIO1 rising edge that occurred during the draw
      int startState = radio.startReceive();
      if (startState != RADIOLIB_ERR_NONE) {
        Serial.printf("[LoRa] startReceive FAILED after draw, code: %d\n", startState);
      }
      lastRxArmTime = millis();
      // If the flag got set during the draw, process it immediately next loop
    }
  }
}
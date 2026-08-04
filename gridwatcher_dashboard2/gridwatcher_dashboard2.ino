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
#include "wallpaper.h"

// WiFi OTA — only starts when user long-presses BOOT button
const char* otaSSID = "GridWatcher-Home";
const char* otaPass = "gridwatcher123";
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

// Onboard LED for visual RX feedback
#ifndef LED_BUILTIN
  #define LED_BUILTIN 8
#endif
#define LED_PIN    LED_BUILTIN
#define LED_RX_MS  50     // Blip on good packet received
#define LED_ERR_MS 200    // Longer pulse on RX error or watchdog re-arm
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
// OTA MODE — activated by long-pressing BOOT button (3 seconds)
// ==============================================================================
void startOTAMode() {
  if (otaModeActive) return;
  otaModeActive = true;

  Serial.println("[OTA] Long press detected — starting WiFi OTA mode...");

  // Show OTA mode on screen
  canvas.fillScreen(0x0000);
  canvas.setTextColor(0xFFFF);
  canvas.setTextSize(1);
  canvas.setCursor(2, 60);
  canvas.print("OTA MODE");
  canvas.setCursor(2, 75);
  canvas.print("Connecting...");
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
  digitalWrite(PIN_BLK, HIGH);

  WiFi.mode(WIFI_STA);
  WiFi.begin(otaSSID, otaPass);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 8000) {
    delay(200);
  }

  otaServer.on("/update", HTTP_GET, []() {
    otaServer.send(200, "text/html", otaHTML);
  });

  otaServer.on("/update", HTTP_POST, []() {
    otaServer.send(200, "text/plain", (Update.hasError()) ? "FAIL" : "OK");
    delay(500);
    ESP.restart();
  }, []() {
    HTTPUpload& upload = otaServer.upload();
    if (upload.status == UPLOAD_FILE_START) {
      if (!Update.begin(UPDATE_SIZE_UNKNOWN)) Update.printError(Serial);
    } else if (upload.status == UPLOAD_FILE_WRITE) {
      if (Update.write(upload.buf, upload.currentSize) != upload.currentSize)
        Update.printError(Serial);
    } else if (upload.status == UPLOAD_FILE_END) {
      if (Update.end(true))
        Serial.printf("[OTA] Flashed %u bytes. Rebooting...\n", upload.totalSize);
      else
        Update.printError(Serial);
    }
  });

  otaServer.begin();

  // Show IP on screen so you know where to connect
  canvas.fillScreen(0x0000);
  canvas.setTextColor(0xFFFF);
  canvas.setCursor(2, 50);
  canvas.print("OTA READY");
  canvas.setCursor(2, 65);
  canvas.setTextColor(0x4D3F);
  canvas.print("Connect to:");
  canvas.setCursor(2, 80);
  canvas.setTextColor(0xFFFF);
  if (WiFi.status() == WL_CONNECTED) {
    canvas.print(WiFi.localIP().toString().c_str());
  } else {
    canvas.print("WIFI FAIL");
  }
  canvas.setCursor(2, 100);
  canvas.setTextColor(0x738E);
  canvas.print("then visit");
  canvas.setCursor(2, 115);
  canvas.print("<IP>/update");
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
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

  // Use RadioLib's own API to pause/resume the interrupt — safer than raw detach/attach
  // which bypasses RadioLib's internal state tracking and causes missed packets.
  radio.clearPacketReceivedAction();
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
  radio.setPacketReceivedAction(onPacketReceived);
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

  // Hard reset the radio before init — clears any stuck state from previous flash
  pinMode(LORA_RST, OUTPUT);
  digitalWrite(LORA_RST, LOW);
  delay(20);
  digitalWrite(LORA_RST, HIGH);
  delay(100); // Let SX1262 fully settle after reset

  int state = radio.begin(868.0, 125.0, 10, 7, 0x12, 10, 8, 1.6, false);
  if (state == RADIOLIB_ERR_NONE) {
    radio.setDio2AsRfSwitch(true);
    radio.setPacketReceivedAction(onPacketReceived);
    delay(50); // Brief settle before arming receive
    radio.startReceive();
    lastRxArmTime = millis();
    Serial.println("[LoRa] Initialized and listening.");
  } else {
    Serial.printf("[LoRa] Init failed, code: %d\n", state);
  }

  tft.init(76, 284);
  tft.setRotation(2);
  tft.invertDisplay(false);
  tft.fillScreen(ST77XX_BLACK);

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

  // RX Watchdog — if receivedFlag hasn't been set in RX_WATCHDOG_MS,
  // the radio may have gotten stuck. Force re-arm startReceive().
  if (millis() - lastRxArmTime > RX_WATCHDOG_MS && !receivedFlag) {
    Serial.println("[LoRa] RX watchdog: re-arming startReceive()...");
    radio.startReceive();
    lastRxArmTime = millis();
    // Double-pulse so you can see self-heals without opening the terminal
    digitalWrite(LED_PIN, HIGH);
    ledOffMs = millis() + LED_ERR_MS;
  }

  if (receivedFlag) {
    receivedFlag  = false;
    lastRxArmTime = millis(); // Reset watchdog on each real packet flag

    // Use String for readData — safer for variable-length LoRa packets
    String str;
    int state = radio.readData(str);

    // Restart receive IMMEDIATELY after reading — minimal RX gap
    radio.startReceive();
    lastRxArmTime = millis();

    if (state == RADIOLIB_ERR_NONE) {
      str.trim();
      Serial.print("RX: "); Serial.println(str);
      // Short blip — good packet
      digitalWrite(LED_PIN, HIGH);
      ledOffMs = millis() + LED_RX_MS;

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
    }
  }

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
  // This gives the radio time to return to RX mode before we take the SPI bus.
  if (newDataFlag && screenAwake &&
      (millis() - dataReceivedMs >= DRAW_DELAY_MS)) {
    newDataFlag = false;
    drawFrame();
  }
}
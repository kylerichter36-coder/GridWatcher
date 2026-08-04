/*
  GRIDWATCHR Handheld Dashboard v2 (Complete UI Redesign)
  FireBeetle 2 ESP32-C6 + 76x284 long-strip ST7789 TFT (portrait)

  Layout (top to bottom):
  ┌────────────────────────────┐
  │ GRIDWATCHR        HH:MM:SS│  Title + uptime
  ├────────────────────────────┤
  │ WIRELESS                   │  LoRa, Cell, Loss
  ├────────────────────────────┤
  │ READINGS                   │  Voltage (big), Freq, V graph
  ├────────────────────────────┤
  │ BATTERIES                  │  Hand, Home, Phone
  ├────────────────────────────┤
  │ AI PREDICT                 │  State + risk bar
  ├────────────────────────────┤
  │ LIVE / OFFLINE Xs          │  Status footer
  └────────────────────────────┘

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

// WiFi OTA Credentials (connects to Home Sender AP)
const char* otaSSID = "GridWatcher-Home";
const char* otaPass = "gridwatcher123";
WebServer otaServer(80);

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
int   linkQual  = 0;
float pktLoss   = 0.0;

// AI Prediction
int   aiRisk = 0;           // 0-100% outage risk
const char* aiState = "WAIT";

int batteryPercent = 0;
int batteryMilliVolts = 0;
bool isCharging = false;
#define BATT_GOOD_PCT 60
#define BATT_WARN_PCT 30

// Home unit's battery, received over LoRa (-1 = never heard from it)
int homeBatteryPercent = -1;

// Phone battery, received over LoRa via PB: field (-1 = no reading)
int phoneBatteryPercent = -1;

// Cellular signal strength (dBm), relayed: phone -> ESP32 AP -> LoRa
int cellSignalDbm = -999;

// Link freshness
unsigned long lastPacketMillis = 0;
bool linkAlive = false;
#define LINK_TIMEOUT_MS 3000

// Screen sleep
bool screenAwake = true;
unsigned long lastActivity = 0;
const unsigned long SLEEP_MS = 5UL * 60UL * 1000UL;

// Voltage history graph (ONLY graph on screen)
#define HIST_LEN 40
float vHist[HIST_LEN];
int histIdx = 0;

// AI: rolling voltage/freq history for anomaly detection
#define AI_HIST_LEN 10
float aiVoltHist[AI_HIST_LEN];
float aiFreqHist[AI_HIST_LEN];
int aiHistIdx = 0;

// Update Timers & Stats
unsigned long lastUpdate = 0;
const unsigned long UPDATE_MS = 1000;
bool btnLastRaw = HIGH;
unsigned long btnLastChange = 0;
const unsigned long DEBOUNCE_MS = 40;

// LoRa Tracking Stats
unsigned long lastExpectedSeq = 0;
int packetsReceivedThisSecond = 0;
float rxRate = 0.0;
long totalLostPackets = 0;
long totalExpectedPackets = 0;

// ---------- Interrupt-driven receive flag ----------
volatile bool receivedFlag = false;

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void onPacketReceived(void) {
  receivedFlag = true;
}

// ---------- Helper Functions ----------

void pollBootButton() {
  bool raw = digitalRead(PIN_BOOT_BTN);
  if (raw != btnLastRaw) {
    btnLastChange = millis();
    btnLastRaw = raw;
  }
  static bool armed = true;
  if (millis() - btnLastChange > DEBOUNCE_MS) {
    if (raw == LOW && armed) {
      armed = false;
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
    } else if (raw == HIGH) {
      armed = true;
    }
  }
}

void readBattery() {
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
  static int historyIdx = 0;
  static unsigned long lastHistTime = 0;

  if (millis() - lastHistTime >= 1000 || lastHistTime == 0) {
    lastHistTime = millis();
    vHistory[historyIdx] = batteryMilliVolts;
    historyIdx = (historyIdx + 1) % 10;
  }

  int oldestSample = vHistory[historyIdx];
  int trendDelta = (oldestSample > 0) ? (batteryMilliVolts - oldestSample) : 0;

  if (trendDelta >= 15 || (batteryMilliVolts >= 4150 && trendDelta >= -5)) {
    isCharging = true;
  } else if (trendDelta <= 2 && batteryMilliVolts < 4120) {
    isCharging = false;
  }
}

// ---------- AI Risk Calculation ----------
void updateAIRisk() {
  // Rule-based heuristic: scores voltage deviation, frequency deviation,
  // and cell signal weakness. Will be replaced by ML model later.
  
  float vRisk = 0.0;
  float fRisk = 0.0;
  float cRisk = 0.0;

  // Voltage risk: how far from nominal 230V
  float vDev = abs(voltage - 230.0);
  if (vDev > 20.0) vRisk = 100.0;
  else if (vDev > 10.0) vRisk = map(vDev * 10, 100, 200, 30, 80);
  else if (vDev > 5.0) vRisk = map(vDev * 10, 50, 100, 10, 30);
  else vRisk = 0.0;

  // Frequency risk: how far from nominal 50Hz
  float fDev = abs(freq_Hz - 50.0);
  if (fDev > 2.0) fRisk = 100.0;
  else if (fDev > 0.5) fRisk = map(fDev * 100, 50, 200, 20, 80);
  else fRisk = 0.0;

  // Cell signal risk: weak signal = harder to alert
  if (cellSignalDbm == -999) cRisk = 10.0;
  else if (cellSignalDbm < -110) cRisk = 40.0;
  else if (cellSignalDbm < -100) cRisk = 15.0;
  else cRisk = 0.0;

  // Weighted combination
  float totalRisk = (vRisk * 0.45) + (fRisk * 0.40) + (cRisk * 0.15);
  aiRisk = constrain((int)totalRisk, 0, 100);

  // Determine state label
  if (!linkAlive) {
    aiState = "NO LINK";
  } else if (aiRisk >= 60) {
    aiState = "OUTAGE";
  } else if (aiRisk >= 25) {
    aiState = "WARNING";
  } else {
    aiState = "STABLE";
  }
}

// ---------- Battery Icon Drawing ----------
void drawBatteryIcon(int x, int y, int percent, bool charging) {
  uint16_t col = (percent >= BATT_GOOD_PCT) ? COL_GOOD
               : (percent >= BATT_WARN_PCT) ? COL_WARN
               : COL_CRIT;
  canvas.drawRect(x, y, 16, 8, col);
  canvas.drawFastVLine(x + 16, y + 2, 4, col);
  int fillW = (14 * percent) / 100;
  canvas.fillRect(x + 1, y + 1, fillW, 6, col);
  if (charging) {
    canvas.drawLine(x + 9, y - 1, x + 5, y + 4, cur.white);
    canvas.drawLine(x + 5, y + 4, x + 8, y + 4, cur.white);
    canvas.drawLine(x + 8, y + 4, x + 4, y + 9, cur.white);
  }
}

// Small battery icon for the BATTERIES section (compact, with label)
void drawBatteryRow(int x, int y, int percent, bool charging, const char* label) {
  // Draw icon
  uint16_t col = (percent >= BATT_GOOD_PCT) ? COL_GOOD
               : (percent >= BATT_WARN_PCT) ? COL_WARN
               : COL_CRIT;
  
  if (percent < 0) {
    // No data yet
    canvas.setTextColor(cur.dim);
    canvas.setCursor(x, y);
    canvas.printf("%s --", label);
    return;
  }

  canvas.drawRect(x, y, 14, 7, col);
  canvas.drawFastVLine(x + 14, y + 2, 3, col);
  int fillW = (12 * percent) / 100;
  canvas.fillRect(x + 1, y + 1, fillW, 5, col);
  
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

void drawWallpaper() {
  const uint16_t* src = darkMode ? wallpaper_dark : wallpaper_light;
  for (int y = 0; y < SCR_H; y++) {
    for (int x = 0; x < SCR_W; x++) {
      canvas.drawPixel(x, y, pgm_read_word(&src[y * SCR_W + x]));
    }
  }
}

// ================================================================
// drawFrame() — REDESIGNED UI
// ================================================================
void drawFrame() {
  drawWallpaper();
  canvas.setTextWrap(false);

  int y = 0;

  // ============================================================
  // TITLE BAR: "GRIDWATCHR" centered
  // ============================================================
  canvas.setTextSize(1);
  canvas.setTextColor(cur.white);
  canvas.setCursor(2, 2);
  canvas.print("GRIDWATCHR");
  
  canvas.drawFastHLine(0, 11, SCR_W, cur.line);

  // ============================================================
  // SECTION 1: WIRELESS
  // ============================================================
  y = 14;
  canvas.setTextColor(cur.accent);
  canvas.setCursor(2, y);
  canvas.print("WIRELESS");
  canvas.drawFastHLine(0, y + 9, SCR_W, cur.line);

  // LoRa link: dBm + quality on one line
  y += 12;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, y);
  canvas.print("LORA");
  canvas.setTextColor(cur.text);
  canvas.setCursor(28, y);
  if (linkAlive) {
    canvas.printf("%ddBm", rssi_dBm);
  } else {
    canvas.print("--");
  }

  y += 9;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, y);
  canvas.print("QUAL");
  canvas.setTextColor(cur.text);
  canvas.setCursor(28, y);
  if (linkAlive) {
    canvas.printf("%d%%", linkQual);
  } else {
    canvas.print("--");
  }

  // Cell signal
  y += 9;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, y);
  canvas.print("CELL");
  canvas.setTextColor(cur.text);
  canvas.setCursor(28, y);
  if (cellSignalDbm != -999 && linkAlive) {
    canvas.printf("%ddBm", cellSignalDbm);
  } else {
    canvas.print("--");
  }

  // Packet loss
  y += 9;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, y);
  canvas.print("LOSS");
  canvas.setTextColor(cur.text);
  canvas.setCursor(28, y);
  canvas.printf("%.1f%%", pktLoss);

  y += 10;
  canvas.drawFastHLine(0, y, SCR_W, cur.line);

  // ============================================================
  // SECTION 2: READINGS
  // ============================================================
  y += 3;
  canvas.setTextColor(cur.accent);
  canvas.setCursor(2, y);
  canvas.print("READINGS");
  canvas.drawFastHLine(0, y + 9, SCR_W, cur.line);

  // Voltage — big font
  y += 12;
  canvas.setTextSize(2);
  canvas.setTextColor(cur.white);
  canvas.setCursor(2, y);
  canvas.printf("%.1fV", voltage);
  canvas.setTextSize(1);

  // Frequency
  y += 18;
  canvas.setTextColor(cur.text);
  canvas.setCursor(2, y);
  canvas.printf("%.2f Hz", freq_Hz);

  // Voltage history graph (ONLY graph on screen)
  y += 12;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, y);
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
    int x = gx0 + (i * gw) / (HIST_LEN - 1);
    int py = gy0 + gh - (int)(((vHist[idx] - vmin) / (vmax - vmin)) * gh);
    py = constrain(py, gy0, gy0 + gh - 1);
    if (prevX >= 0) canvas.drawLine(prevX, prevY, x, py, cur.accent);
    prevX = x; prevY = py;
  }

  y = gy0 + gh + 4;
  canvas.drawFastHLine(0, y, SCR_W, cur.line);

  // ============================================================
  // SECTION 3: BATTERIES
  // ============================================================
  y += 3;
  canvas.setTextColor(cur.accent);
  canvas.setCursor(2, y);
  canvas.print("BATTERIES");
  canvas.drawFastHLine(0, y + 9, SCR_W, cur.line);

  // Handheld battery
  y += 12;
  drawBatteryRow(2, y, batteryPercent, isCharging, "HND");

  // Home base battery
  y += 10;
  drawBatteryRow(2, y, homeBatteryPercent, false, "HME");

  // Phone battery
  y += 10;
  drawBatteryRow(2, y, phoneBatteryPercent, false, "PHN");

  y += 11;
  canvas.drawFastHLine(0, y, SCR_W, cur.line);

  // ============================================================
  // SECTION 4: AI PREDICT
  // ============================================================
  y += 3;
  canvas.setTextColor(cur.accent);
  canvas.setCursor(2, y);
  canvas.print("AI PREDICT");
  canvas.drawFastHLine(0, y + 9, SCR_W, cur.line);

  // State label
  y += 12;
  uint16_t stateCol = COL_GOOD;
  if (aiRisk >= 60) stateCol = COL_CRIT;
  else if (aiRisk >= 25) stateCol = COL_WARN;
  
  canvas.setTextColor(stateCol);
  canvas.setCursor(2, y);
  canvas.print(aiState);
  
  canvas.setTextColor(cur.text);
  canvas.setCursor(50, y);
  canvas.printf("%d%%", aiRisk);

  // Risk bar
  y += 10;
  int bx = 2, bw = SCR_W - 4, bh = 6;
  canvas.drawRect(bx, y, bw, bh, cur.line);
  int fillW = ((bw - 2) * aiRisk) / 100;
  uint16_t barCol = COL_GOOD;
  if (aiRisk >= 60) barCol = COL_CRIT;
  else if (aiRisk >= 25) barCol = COL_WARN;
  canvas.fillRect(bx + 1, y + 1, fillW, bh - 2, barCol);

  y += bh + 4;
  canvas.drawFastHLine(0, y, SCR_W, cur.line);

  // ============================================================
  // FOOTER: Connection status + uptime
  // ============================================================
  y += 3;
  canvas.setCursor(2, y);
  if (lastPacketMillis == 0) {
    canvas.setTextColor(cur.dim);
    canvas.print("NO DATA YET");
  } else if (!linkAlive) {
    canvas.setTextColor(COL_CRIT);
    unsigned long secs = (millis() - lastPacketMillis) / 1000;
    canvas.printf("OFFLINE %lus", secs);
  } else {
    canvas.setTextColor(COL_GOOD);
    canvas.print("LIVE");
    canvas.setTextColor(cur.dim);
    canvas.printf(" %.0fpps", rxRate);
  }

  // Uptime on second footer line
  y += 10;
  unsigned long upSecs = millis() / 1000UL;
  unsigned long upH = upSecs / 3600UL;
  unsigned long upM = (upSecs % 3600UL) / 60UL;
  unsigned long upS = upSecs % 60UL;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, y);
  canvas.printf("UP %02lu:%02lu:%02lu", upH, upM, upS);

  // Push to display
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
}

// ---------- Setup & Loop ----------

void setup() {
  Serial.begin(115200);
  delay(3000);

  Serial.println("\n[Handheld] Booting GridWatchr Dashboard v2...");

  pinMode(PIN_BLK, OUTPUT);
  digitalWrite(PIN_BLK, HIGH);
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);
  analogReadResolution(12);

  SPI.begin(23, 21, 22);

  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 10, 8, 1.6, false);
  if (state == RADIOLIB_ERR_NONE) {
    radio.setDio2AsRfSwitch(true);
    radio.setPacketReceivedAction(onPacketReceived);
    radio.startReceive();
    Serial.println("[LoRa] Initialized successfully and listening.");
  } else {
    Serial.print("[LoRa] Initialization failed, code: ");
    Serial.println(state);
  }

  tft.init(76, 284);
  tft.setRotation(2);
  tft.invertDisplay(false);
  tft.fillScreen(ST77XX_BLACK);

  // Connect to GridWatcher-Home WiFi for Wireless OTA Updates
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(otaSSID, otaPass);
  Serial.println("[WiFi] Connecting to GridWatcher-Home AP for Wireless OTA...");

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
      Serial.printf("[OTA] Flashing dashboard: %s\n", upload.filename.c_str());
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

  otaServer.begin();

  for (int i = 0; i < HIST_LEN; i++) vHist[i] = 0.0;
  for (int i = 0; i < AI_HIST_LEN; i++) { aiVoltHist[i] = 230.0; aiFreqHist[i] = 50.0; }

  readBattery();
  lastActivity = millis();
  drawFrame();
}

void loop() {
  otaServer.handleClient();
  pollBootButton();

  if (receivedFlag) {
    receivedFlag = false;
    String str;
    int state = radio.readData(str);

    if (state == RADIOLIB_ERR_NONE) {
      str.trim();

      Serial.print("Received Packet: ");
      Serial.println(str);

      int vIdx = str.indexOf("V:");
      int fIdx = str.indexOf(",F:");
      int bIdx = str.indexOf(",B:");
      int cellIdx = str.indexOf(",S:");
      int pbIdx = str.indexOf(",PB:");
      int sIdx = str.indexOf(",SEQ:");

      if (vIdx >= 0 && fIdx > vIdx && sIdx > fIdx) {
        packetsReceivedThisSecond++;
        lastPacketMillis = millis();

        voltage = str.substring(vIdx + 2, fIdx).toFloat();
        freq_Hz = str.substring(fIdx + 3, (bIdx > fIdx ? bIdx : sIdx)).toFloat();

        // Parse home battery (B:)
        if (bIdx > fIdx) {
          int bEnd = (cellIdx > bIdx) ? cellIdx : sIdx;
          homeBatteryPercent = str.substring(bIdx + 3, bEnd).toInt();
        }

        // Parse cell signal (S:)
        if (cellIdx > fIdx) {
          int sEnd = (pbIdx > cellIdx) ? pbIdx : sIdx;
          cellSignalDbm = str.substring(cellIdx + 3, sEnd).toInt();
        }

        // Parse phone battery (PB:) — NEW
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
          pktLoss = ((float)totalLostPackets / (float)(totalExpectedPackets + totalLostPackets)) * 100.0;
        }

        rssi_dBm = radio.getRSSI();
        float snr = radio.getSNR();
        linkQual = constrain(map(snr, -20, 10, 0, 100), 0, 100);

        histIdx = (histIdx + 1) % HIST_LEN;
        vHist[histIdx] = voltage;

        // Feed AI history
        aiVoltHist[aiHistIdx] = voltage;
        aiFreqHist[aiHistIdx] = freq_Hz;
        aiHistIdx = (aiHistIdx + 1) % AI_HIST_LEN;
      }
    } else {
      Serial.print("Packet read error code: ");
      Serial.println(state);
    }

    radio.startReceive();
  }

  // Auto-sleep after SLEEP_MS of no button activity
  if (screenAwake && (millis() - lastActivity > SLEEP_MS)) {
    screenAwake = false;
    digitalWrite(PIN_BLK, LOW);
  }

  if (millis() - lastUpdate >= UPDATE_MS) {
    lastUpdate = millis();

    rxRate = packetsReceivedThisSecond;
    packetsReceivedThisSecond = 0;

    bool wasAlive = linkAlive;
    linkAlive = (lastPacketMillis != 0) && (millis() - lastPacketMillis < LINK_TIMEOUT_MS);
    if (!linkAlive) {
      linkQual = 0;
    }

    // Wake the screen on a disconnect OR reconnect
    if (wasAlive != linkAlive) {
      screenAwake = true;
      digitalWrite(PIN_BLK, HIGH);
      lastActivity = millis();
    }

    // Update AI risk calculation
    updateAIRisk();

    readBattery();
    if (screenAwake) drawFrame();
  }
}
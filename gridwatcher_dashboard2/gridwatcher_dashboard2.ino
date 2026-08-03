/*
  GridWatcher: Handheld Dashboard (Fully Synchronized LoRa Receiver)
  Hardware: FireBeetle 2 ESP32-C6 + 76x284 long-strip ST7789 TFT + SX1262
  Description: A standalone off-grid hardware receiver that parses LoRa telemetry 
  from the base station and renders a custom UI tracking AC voltage, frequencies, 
  and cellular signal strength.
*/

#include <SPI.h>
#include <Adafruit_GFX.h>
#include <Adafruit_ST7789.h>
#include <RadioLib.h>
#include "wallpaper.h"

// ==============================================================================
// [1] HARDWARE & PIN DEFINITIONS
// ==============================================================================

// --- Shared SPI Bus (CRITICAL FIX) ---
// The TFT display and the LoRa radio share the same hardware SPI bus (SCK/MOSI).
// Using hardware SPI (instead of Adafruit's software bit-banged SPI constructor) 
// prevents the display from hijacking the pins and crashing the radio.
#define PIN_SCL   23   // Shared LoRa SCK
#define PIN_SDA   22   // Shared LoRa MOSI
#define PIN_RES   2    // TFT Reset (Moved off GPIO8 to avoid boot-strapping conflicts)
#define PIN_DC    20   // TFT Data/Command
#define PIN_CS    19   // TFT Chip Select
#define PIN_BLK   18   // TFT Backlight Control
#define PIN_BAT   0    // Onboard Battery ADC
#define PIN_BOOT_BTN 9 // Hardware wake/theme toggle button

// --- LoRa Control Pins ---
#define LORA_CS   14
#define LORA_DIO1 4
#define LORA_RST  1
#define LORA_BUSY 5
// RXEN/TXEN logic is driven internally by the SX1262's own DIO2 pin.

Adafruit_ST7789 tft = Adafruit_ST7789(&SPI, PIN_CS, PIN_DC, PIN_RES);
SX1262 radio = new Module(LORA_CS, LORA_DIO1, LORA_RST, LORA_BUSY);

#define SCR_W 76
#define SCR_H 284
GFXcanvas16 canvas(SCR_W, SCR_H);

// ==============================================================================
// [2] UI THEME & STATE VARIABLES
// ==============================================================================

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

// ==============================================================================
// [3] TELEMETRY GLOBALS
// ==============================================================================

// Grid & RF Stats
float voltage   = 0.0;
float freq_Hz   = 0.0;
int   rssi_dBm  = 0;
int   linkQual  = 0;
float txRate    = 0.0;
float rxRate    = 0.0;
float pktLoss   = 0.0;
int   aiConfidence = 0;
const char* aiState = "WAIT..";

// Battery States
int batteryPercent = 0;
int batteryMilliVolts = 0;
int prevBatteryMilliVolts = 0;
bool isCharging = false;
#define BATT_GOOD_PCT 60
#define BATT_WARN_PCT 30
int homeBatteryPercent = -1; // Base station battery (received via LoRa)

// Cellular Signal History
int cellSignalDbm = -999;
#define CELL_HIST_LEN 40
int cellHist[CELL_HIST_LEN];

// Link Freshness Tracking
unsigned long lastPacketMillis = 0;
bool linkAlive = false;
#define LINK_TIMEOUT_MS 3000  // Base station transmits every 1s. >3s = dead link.

// Sleep & Power Management
bool screenAwake = true;
unsigned long lastActivity = 0;
const unsigned long SLEEP_MS = 5UL * 60UL * 1000UL;  // 5 minute auto-sleep

// Voltage History
#define HIST_LEN 40
float vHist[HIST_LEN];
int histIdx = 0;

// Update Timers
unsigned long lastUpdate = 0;
const unsigned long UPDATE_MS = 1000;
bool btnLastRaw = HIGH;
unsigned long btnLastChange = 0;
const unsigned long DEBOUNCE_MS = 40;

// Packet Tracking (For Loss Calculation)
unsigned long lastExpectedSeq = 0;
int packetsReceivedThisSecond = 0;
long totalLostPackets = 0;
long totalExpectedPackets = 0;

// ==============================================================================
// [4] HARDWARE INTERRUPTS (ISR)
// ==============================================================================

// CRITICAL: This flag is set by the radio module's DIO1 pin going HIGH when 
// a complete packet successfully lands in the SX1262's internal buffer.
// We keep the ISR extremely short to prevent memory/timing crashes (ICACHE_RAM_ATTR).
volatile bool receivedFlag = false;

#if defined(ESP8266) || defined(ESP32)
  ICACHE_RAM_ATTR
#endif
void onPacketReceived(void) {
  receivedFlag = true;
}

// ==============================================================================
// [5] UTILITY FUNCTIONS
// ==============================================================================

/**
 * Polls the physical BOOT button. 
 * - If screen is asleep: Wakes the screen.
 * - If screen is awake: Toggles the Light/Dark theme.
 */
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
        digitalWrite(PIN_BLK, HIGH); // Turn backlight on
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

/**
 * Reads local battery voltage with Exponential Moving Average (EMA) noise filtering.
 * Uses a 10-second rolling trend window with hysteresis to accurately detect 
 * charging without flickering due to ADC noise.
 */
void readBattery() {
  // Take 20 ADC samples to smooth out raw ADC noise
  long sum = 0;
  for (int i = 0; i < 20; i++) {
    sum += analogReadMilliVolts(PIN_BAT);
    delayMicroseconds(250);
  }
  int rawMv = (sum / 20) * 2; // Voltage divider math (1:1 divider on FireBeetle 2)

  // Exponential Moving Average filter to smooth ADC jitter
  static float smoothedMv = 0;
  if (smoothedMv == 0) smoothedMv = rawMv;
  else smoothedMv = (smoothedMv * 0.85) + (rawMv * 0.15);

  batteryMilliVolts = (int)smoothedMv;

  // Percentage calculation based on standard 3.3V-4.2V LiPo curve
  float pct = ((float)batteryMilliVolts - 3300.0) / (4200.0 - 3300.0) * 100.0;
  batteryPercent = constrain((int)pct, 0, 100);

  // --- Rolling 10-Second Voltage Trend for Charging Detection ---
  static int vHistory[10] = {0};
  static int historyIdx = 0;
  static unsigned long lastHistTime = 0;

  if (millis() - lastHistTime >= 1000 || lastHistTime == 0) {
    lastHistTime = millis();
    vHistory[historyIdx] = batteryMilliVolts;
    historyIdx = (historyIdx + 1) % 10;
  }

  // Compare current voltage against 10-second historical baseline
  int oldestSample = vHistory[historyIdx];
  int trendDelta = (oldestSample > 0) ? (batteryMilliVolts - oldestSample) : 0;

  // Hysteresis Latching: Prevents charging icon from flickering randomly
  if (trendDelta >= 15 || (batteryMilliVolts >= 4150 && trendDelta >= -5)) {
    isCharging = true;
  } else if (trendDelta <= 2 && batteryMilliVolts < 4120) {
    isCharging = false;
  }
}

// ==============================================================================
// [6] TFT UI RENDERING ENGINE
// ==============================================================================

void drawBatteryIcon(int x, int y, int percent, bool charging) {
  uint16_t col = (percent >= BATT_GOOD_PCT) ? COL_GOOD
               : (percent >= BATT_WARN_PCT) ? COL_WARN
               : COL_CRIT;
  canvas.drawRect(x, y, 16, 8, col);
  canvas.drawFastVLine(x + 16, y + 2, 4, col);
  int fillW = (14 * percent) / 100;
  canvas.fillRect(x + 1, y + 1, fillW, 6, col);
  
  if (charging) { // Draw a small lightning bolt
    canvas.drawLine(x + 9, y - 1, x + 5, y + 4, cur.white);
    canvas.drawLine(x + 5, y + 4, x + 8, y + 4, cur.white);
    canvas.drawLine(x + 8, y + 4, x + 4, y + 9, cur.white);
  }
}

void drawWallpaper() {
  const uint16_t* src = darkMode ? wallpaper_dark : wallpaper_light;
  for (int y = 0; y < SCR_H; y++) {
    for (int x = 0; x < SCR_W; x++) {
      canvas.drawPixel(x, y, pgm_read_word(&src[y * SCR_W + x]));
    }
  }
}

/**
 * Draws the entire UI layout into the GFX canvas memory buffer, then pushes 
 * the entire buffer to the TFT screen over SPI in one fast block transfer.
 * This prevents the screen from flickering.
 */
void drawFrame() {
  drawWallpaper();
  canvas.setTextWrap(false);

  // ---- Title ----
  canvas.setTextSize(1);
  canvas.setTextColor(cur.white);
  canvas.setCursor(2, 2);
  canvas.print("GRIDWATCHR");
  canvas.drawFastHLine(0, 11, SCR_W, cur.line);

  // ---- Battery ----
  drawBatteryIcon(2, 14, batteryPercent, isCharging);
  canvas.setTextColor(cur.text);
  canvas.setCursor(22, 15);
  canvas.printf("%d%%", batteryPercent);

  // Base Station Battery
  canvas.setTextColor(linkAlive ? cur.accent : cur.dim);
  canvas.setCursor(46, 15);
  if (homeBatteryPercent >= 0 && linkAlive) {
    canvas.printf("H%d%%", homeBatteryPercent);
  } else {
    canvas.print("H--");
  }
  canvas.drawFastHLine(0, 24, SCR_W, cur.line);

  // ---- Link Summary ----
  canvas.setTextColor(cur.accent);
  canvas.setCursor(2, 27);
  if (linkAlive) canvas.printf("HOME %ddBm", rssi_dBm);
  else canvas.print("HOME --");
  canvas.drawFastHLine(0, 37, SCR_W, cur.line);

  // ---- Link Stats ----
  int ly = 40;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, ly);      canvas.print("LINK");
  canvas.setTextColor(cur.text);
  canvas.setCursor(30, ly);
  if (linkAlive) canvas.printf("%ddBm", rssi_dBm); else canvas.print("--");

  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, ly + 9);  canvas.print("QUAL");
  canvas.setTextColor(cur.text);
  canvas.setCursor(30, ly + 9);
  if (linkAlive) canvas.printf("%d%%", linkQual); else canvas.print("--");

  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, ly + 18); canvas.print("TX");
  canvas.setTextColor(cur.text);
  canvas.setCursor(30, ly + 18);canvas.printf("%.2f", txRate);

  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, ly + 27); canvas.print("RX");
  canvas.setTextColor(cur.text);
  canvas.setCursor(30, ly + 27);canvas.printf("%.2f", rxRate);

  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, ly + 36); canvas.print("LOSS");
  canvas.setTextColor(cur.text);
  canvas.setCursor(30, ly + 36);canvas.printf("%.1f%%", pktLoss);

  canvas.drawFastHLine(0, ly + 47, SCR_W, cur.line);

  // ---- Electrical Telemetry ----
  int ey = ly + 50;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, ey);
  canvas.print("VOLTAGE");

  canvas.setTextSize(2);
  canvas.setTextColor(cur.white);
  canvas.setCursor(2, ey + 8);
  canvas.printf("%.1fV", voltage);
  canvas.setTextSize(1);

  canvas.setTextColor(cur.text);
  canvas.setCursor(2, ey + 24); canvas.printf("FREQ %.2fHz", freq_Hz);

  canvas.drawFastHLine(0, ey + 34, SCR_W, cur.line);

  // ---- Voltage History Graph ----
  int gy = ey + 37;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, gy);
  canvas.print("V HISTORY");

  int gx0 = 3, gy0 = gy + 9, gw = SCR_W - 6, gh = 44;
  canvas.drawRect(gx0 - 1, gy0 - 1, gw + 2, gh + 2, cur.line);

  // Dynamically scale graph axes based on min/max of current history
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
    int y = gy0 + gh - (int)(((vHist[idx] - vmin) / (vmax - vmin)) * gh);
    y = constrain(y, gy0, gy0 + gh - 1);
    if (prevX >= 0) canvas.drawLine(prevX, prevY, x, y, cur.accent);
    prevX = x; prevY = y;
  }

  canvas.drawFastHLine(0, gy0 + gh + 8, SCR_W, cur.line);

  // ---- Simulated AI Prediction ----
  int ay = gy0 + gh + 11;
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, ay);
  canvas.print("AI PREDICT");

  canvas.setTextColor(cur.accent);
  canvas.setCursor(2, ay + 9);
  canvas.printf("[%s] %d%%", aiState, aiConfidence);

  int bx = 2, by = ay + 19, bw = SCR_W - 4, bh = 6;
  canvas.drawRect(bx, by, bw, bh, cur.line);
  int fillW = (bw - 2) * aiConfidence / 100;
  canvas.fillRect(bx + 1, by + 1, fillW, bh - 2, cur.accent);

  canvas.drawFastHLine(0, ay + 33, SCR_W, cur.line);

  // ---- System Uptime ----
  canvas.setTextColor(cur.dim);
  canvas.setCursor(2, ay + 36);
  canvas.print("UPTIME");

  canvas.setTextColor(cur.text);
  canvas.setCursor(2, ay + 45);
  unsigned long upSecs = millis() / 1000UL;
  unsigned long upH = upSecs / 3600UL;
  unsigned long upM = (upSecs % 3600UL) / 60UL;
  unsigned long upS = upSecs % 60UL;
  canvas.printf("UP %02lu:%02lu:%02lu", upH, upM, upS);

  canvas.drawFastHLine(0, ay + 55, SCR_W, cur.line);

  // ---- Cellular Signal History ----
  int ny = ay + 58;
  canvas.setCursor(2, ny);
  if (lastPacketMillis == 0) {
    canvas.setTextColor(cur.dim);
    canvas.print("NO DATA YET");
  } else if (!linkAlive) {
    canvas.setTextColor(COL_CRIT);
    unsigned long secs = (millis() - lastPacketMillis) / 1000;
    canvas.printf("OFFLINE %lus", secs);
  } else if (cellSignalDbm != -999) {
    canvas.setTextColor(cur.accent);
    canvas.printf("CELL %ddBm", cellSignalDbm);
  } else {
    canvas.setTextColor(cur.dim);
    canvas.print("CELL --");
  }

  int cgx0 = 3, cgy0 = ny + 9, cgw = SCR_W - 6, cgh = 16;
  canvas.drawRect(cgx0 - 1, cgy0 - 1, cgw + 2, cgh + 2, cur.line);
  {
    int cmin = 999, cmax = -999;
    for (int i = 0; i < CELL_HIST_LEN; i++) {
      if (cellHist[i] == -999) continue;
      if (cellHist[i] < cmin) cmin = cellHist[i];
      if (cellHist[i] > cmax) cmax = cellHist[i];
    }
    if (cmin <= cmax) {
      if (cmax - cmin < 5) { cmax += 3; cmin -= 3; }
      int pX = -1, pY = 0;
      for (int i = 0; i < CELL_HIST_LEN; i++) {
        int idx = (histIdx + i) % CELL_HIST_LEN;
        if (cellHist[idx] == -999) { pX = -1; continue; }
        int x = cgx0 + (i * cgw) / (CELL_HIST_LEN - 1);
        int y = cgy0 + cgh - (int)(((float)(cellHist[idx] - cmin) / (cmax - cmin)) * cgh);
        y = constrain(y, cgy0, cgy0 + cgh - 1);
        if (pX >= 0) canvas.drawLine(pX, pY, x, y, cur.accent);
        pX = x; pY = y;
      }
    }
  }

  // Push buffer to TFT via hardware SPI
  tft.drawRGBBitmap(0, 0, canvas.getBuffer(), SCR_W, SCR_H);
}

// ==============================================================================
// [7] SYSTEM INITIALIZATION
// ==============================================================================

void setup() {
  Serial.begin(115200);
  delay(3000); 

  Serial.println("\n[Handheld] Booting GridWatcher dashboard...");

  pinMode(PIN_BLK, OUTPUT);
  digitalWrite(PIN_BLK, HIGH); // Backlight ON
  pinMode(PIN_BOOT_BTN, INPUT_PULLUP);
  analogReadResolution(12);

  // Initialize shared Hardware SPI
  SPI.begin(23, 21, 22);

  // Initialize RadioLib
  int state = radio.begin(868.0, 125.0, 9, 7, 0x12, 10, 8, 1.6, false);
  if (state == RADIOLIB_ERR_NONE) {
    // Configure internal DIO2 as the RF switch
    radio.setDio2AsRfSwitch(true);
    // Attach ISR to catch incoming packets
    radio.setPacketReceivedAction(onPacketReceived);
    // Start listening asynchronously
    radio.startReceive();
    Serial.println("[LoRa] Initialized successfully and listening.");
  } else {
    Serial.print("[LoRa] Initialization failed, code: ");
    Serial.println(state);
  }

  // Initialize TFT
  tft.init(76, 284);
  tft.setRotation(2);
  tft.invertDisplay(false);
  tft.fillScreen(ST77XX_BLACK);

  // Clear buffers
  for (int i = 0; i < HIST_LEN; i++) vHist[i] = 0.0;
  for (int i = 0; i < CELL_HIST_LEN; i++) cellHist[i] = -999;
  
  readBattery();
  lastActivity = millis();
  drawFrame();
}

// ==============================================================================
// [8] MAIN RUNTIME LOOP
// ==============================================================================

void loop() {
  pollBootButton();
  
  // ISR signaled a packet was received!
  if (receivedFlag) {
    receivedFlag = false;
    String str;
    int state = radio.readData(str);
    
    if (state == RADIOLIB_ERR_NONE) {
      str.trim();
      
      Serial.print("Received Packet: ");
      Serial.println(str);

      // Basic payload parsing (e.g., "V:230.1,F:50.0,B:100,S:-85,SEQ:42")
      int vIdx = str.indexOf("V:");
      int fIdx = str.indexOf(",F:");
      int bIdx = str.indexOf(",B:");
      int cellIdx = str.indexOf(",S:");
      int sIdx = str.indexOf(",SEQ:");
      
      if (vIdx >= 0 && fIdx > vIdx && sIdx > fIdx) {
        packetsReceivedThisSecond++; 
        lastPacketMillis = millis();
        
        voltage   = str.substring(vIdx + 2, fIdx).toFloat();
        freq_Hz   = str.substring(fIdx + 3, (bIdx > fIdx ? bIdx : sIdx)).toFloat();

        if (bIdx > fIdx && sIdx > bIdx) {
          int bEnd = (cellIdx > bIdx && cellIdx < sIdx) ? cellIdx : sIdx;
          homeBatteryPercent = str.substring(bIdx + 3, bEnd).toInt();
        }

        if (cellIdx > fIdx && sIdx > cellIdx) {
          cellSignalDbm = str.substring(cellIdx + 3, sIdx).toInt();
        }

        unsigned long seq = str.substring(sIdx + 5).toInt();
        
        // Calculate packet loss based on expected sequence numbers
        if (lastExpectedSeq != 0 && seq > lastExpectedSeq) {
          totalLostPackets += (seq - lastExpectedSeq);
        }
        totalExpectedPackets++;
        lastExpectedSeq = seq + 1;
        
        if (totalExpectedPackets > 0) {
          pktLoss = ((float)totalLostPackets / (float)(totalExpectedPackets + totalLostPackets)) * 100.0;
        }

        // Fetch RF metadata
        rssi_dBm = radio.getRSSI();
        float snr = radio.getSNR();
        linkQual = constrain(map(snr, -20, 10, 0, 100), 0, 100);
        
        // Update history arrays for graphs
        histIdx = (histIdx + 1) % HIST_LEN;
        vHist[histIdx] = voltage;
        cellHist[histIdx % CELL_HIST_LEN] = cellSignalDbm;
        
        aiState = "LINKED";
        aiConfidence = linkQual;
      }
    } else {
      Serial.print("Packet read error code: ");
      Serial.println(state);
    }
    
    // Resume listening for the next packet
    radio.startReceive();
  }

  // Auto-sleep screen backlight to conserve battery
  if (screenAwake && (millis() - lastActivity > SLEEP_MS)) {
    screenAwake = false;
    digitalWrite(PIN_BLK, LOW);
  }

  // Redraw the UI at 1Hz
  if (millis() - lastUpdate >= UPDATE_MS) {
    lastUpdate = millis();
    
    rxRate = packetsReceivedThisSecond;
    packetsReceivedThisSecond = 0; 

    // Dead-man switch: If no packets arrive for LINK_TIMEOUT_MS, mark offline
    bool wasAlive = linkAlive;
    linkAlive = (lastPacketMillis != 0) && (millis() - lastPacketMillis < LINK_TIMEOUT_MS);
    if (!linkAlive) {
      linkQual = 0;
    }

    // Wake the screen automatically on a disconnect OR a reconnect event
    if (wasAlive != linkAlive) {
      screenAwake = true;
      digitalWrite(PIN_BLK, HIGH);
      lastActivity = millis();
    }

    if (rxRate == 0 && totalExpectedPackets > 0) {
        aiState = "LOSS";
        aiConfidence = 0;
    }
    
    readBattery();
    
    // Only expend CPU cycles drawing the frame if the screen is actually on
    if (screenAwake) drawFrame();
  }
}

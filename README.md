# Grid Watcher: System & Physics Dive

**Author:** Kyle Mason Richter
**Hardware:** FireBeetle 2 ESP32 C6, SX1262 LoRa, ST7789 TFT, ZMPT101B, HLK 10M05, 2000mAh pouch LiPo, MT3608 step up module  
**Software:** ESP IDF/Arduino, RadioLib, Termux (Android), Scikit learn (Python)

**Problem:** Many regions suffer from sudden power outages due to failing and deteriorating infrastructure. There are many early warning signs that a power outage may occur, such as voltage drops, frequency fluctuations, or surges.

**Solution:** Grid Watcher's goal is not to prevent power outages, but to predict them by measuring and learning these early warning signs with onboard sensors. Furthermore, it ensures reliable notification through an off grid LoRa hardware dashboard and an automated SMS gateway.

***

## 1. Hardware Architecture & Power Routing

### 1.1 Microcontroller Selection
Both the transmitter (Base Station) and the receiver (Handheld Dashboard) utilize the **DFRobot FireBeetle 2 ESP32 C6**. This board was chosen specifically for its integrated LiPo charging circuitry (TP4054) and native solar power management. Using this MCU eliminated the need to integrate external charging boards, significantly simplifying the hardware footprint.

### 1.2 Powering the Sensors (MT3608 Step Up)
The AC voltage monitoring relies on ZMPT101B modules, which require a 5V logic/power level. Because the FireBeetle 2 does not backfeed 5V via the VIN pin when running on battery (it only outputs 3.3V max), an **MT3608 step up converter** is implemented. The step up is wired directly to the LiPo battery pins (VBAT) to boost the voltage up to 5V. This ensures the ZMPT101B modules receive clean, reliable power even when running entirely off grid.

### 1.3 Wall Plug Form Factor
The final vision for the Base Station is a compact, self contained unit that plugs directly into a standard wall outlet—similar to a WiFi repeater. It will run off mains power via an HLK 10M05 AC DC module, while seamlessly falling back to the internal LiPo battery during an outage.

***

## 2. Signal Physics: AC Sensing (ZMPT101B Active Module)

*(Note: Currently simulating telemetry while awaiting the physical ZMPT101B active modules to arrive).*

To predict grid failure, we must capture the pristine, unadulterated **50Hz sine wave**. Since the ESP32 C6 ADC cannot read negative voltages, the 240V AC must be galvanically isolated, scaled down, and DC biased to a safe positive range. 

### 2.1 The Active Module (Onboard Op Amp)
Instead of building a custom discrete resistor network for a bare transformer, the system utilizes the **active ZMPT101B module**. This board comes pre equipped with:
* An onboard **LM358 op amp** to actively amplify the tiny secondary current into a measurable voltage wave.
* A built in burden resistor and primary current limiting resistors.
* A built in trimpot to manually adjust the peak to peak amplitude.

### 2.2 DC Bias & 5V Logic Conversion
Because the active module is powered by the 5V MT3608 step up converter, its onboard op amp outputs an analog signal centered exactly at `VCC / 2` (around **2.5V DC** bias). 
Since the ESP32 C6 ADC operates at 3.3V logic (and works best when the wave is centered at 1.65V), the 5V centered analog output from the module is passed through a simple voltage divider on the logic board before hitting the ESP32 pin. This scales the AC wave safely down into the ESP32's 0 to 3.3V window without clipping.

### 2.3 Sampling & Zero Crossing Detection (ZCD)
To satisfy the Nyquist Shannon theorem and detect micro fluctuations (grid noise), the ESP32 samples the ADC at **1,000Hz (1ms intervals)**. Using a Zero Crossing Detection threshold on the newly biased center point and a high resolution hardware timer (`micros()`), the ESP32 calculates frequency via `1 / (Δt * 0.000001)`. This precise timing allows the system to detect a **0.1Hz frequency drop** in real time.

***

## 3. Communication Architecture & RF Engineering

### 3.1 LoRa and RISC V Compatibility
Getting the SX1262 LoRa modules working with the ESP32 C6 presented a major software challenge. Because the ESP32 C6 utilizes a **RISC V core** (rather than the traditional Xtensa architecture), the standard Sandeep Mistry LoRa library failed to compile and caused hard crashes during SPI initialization. 
The radio stack was migrated to **RadioLib**. This required manually mapping all SPI and interrupt pins (NSS, DIO1, NRST, BUSY) and heavily tweaking the initialization timing to prevent boot looping. The radio link is now fully stable and relies on hardware interrupts rather than blocking polling.

### 3.2 Cell Relay & SMS Gateway
The Base Station connects to the home router (STA mode) while simultaneously hosting its own fallback access point (AP mode). It runs a lightweight web server. 
A repurposed smartphone left at home runs Termux and uses HTTP POST to send its current cellular signal strength to the ESP32. **Crucially, this phone acts as an SMS Gateway:** if an outage occurs (or is predicted), it automatically sends a text alert to my personal phone. *(While the LoRa dashboard was a great excuse to learn and play with RF tech, the SMS system ensures I get alerts anywhere).*

***

## 4. The Handheld Receiver Dashboard

Rather than relying purely on a phone for data visualization, the system includes a dedicated, standalone hardware receiver built to operate entirely off grid.

* **Hardware:** FireBeetle 2 ESP32 C6 paired with a 76x284 long strip ST7789 TFT display and an SX1262 LoRa module.
* **SPI Management:** Both the TFT display and the LoRa module share a single, properly configured **hardware SPI bus**, completely avoiding software bit banging conflicts.
* **Power Management:** Implements auto sleep after 5 minutes of inactivity, with a hardware wake and light/dark theme toggle wired to the BOOT pin.

### 4.1 Dashboard UI (v2)
The display is organized into five clean sections, top to bottom:

| Section | Contents |
|---|---|
| **WIRELESS** | LoRa link dBm, link quality %, cell signal dBm, packet loss % |
| **READINGS** | AC voltage (large font), frequency, rolling voltage trend graph |
| **BATTERIES** | Three battery icons: Handheld (HND), Home base (HME), Phone (PHN) |
| **AI PREDICT** | Outage risk state (STABLE / WARNING / OUTAGE), risk percentage bar |
| **FOOTER** | Live/offline status with uptime counter |

### 4.2 LoRa Packet Format (v2)
```
V:<voltage>,F:<freq>,B:<base_batt>,S:<cell_dbm>,PB:<phone_batt>,SEQ:<seq>
```
The `PB:` field carries the phone's battery percentage, relayed through the base station.

***

## 4.5 Live Telemetry Bridge (PC to Phone to ESP32)

The `live_cell_bridge.py` script runs on the PC and acts as the central data pipeline:

1. **Reads cellular signal** from the phone via `adb shell dumpsys telephony.registry`.
2. **Reads phone battery** via `adb shell dumpsys battery`.
3. **Posts both values** to the ESP32 Base Station over the phone's WiFi connection to the AP.
4. **Logs ML training data** (timestamp, voltage, frequency) to a local CSV and to the phone's `/sdcard/Download/` for USB retrieval.
5. **Hosts a web server** on port 8080 for easy CSV download from any device on the network.

***

## 5. The Machine Learning Pipeline (PC Hosted)

Once the ZMPT101B sensors are installed, the ESP32 will stream raw voltage/frequency values to the local WiFi network. A PC running Python fetches this data.

We utilize a **Random Forest Classifier** (`scikit learn`), relying on 100 independent Decision Trees. 
The input features (X vector) include:
1. **RMS Voltage** (1 second rolling window)
2. **Instantaneous Frequency**
3. **Voltage Sag Gradient** (rate of drop over 3 seconds)
4. **Frequency Delta** (Absolute difference between 50Hz and Measured)

The output label (y vector) predicts 0 (Stable) or 1 (Pre Outage). The model learns non linear relationships to flag a "Pre Outage" condition roughly 20 to 60 seconds before the breaker physically trips.

***

## 6. Project Development Roadmap: V1 vs V2

### 6.1 V1: Hand-Soldered Prototype (Current Model)
The current functional prototype is hand-soldered on copper protoboards. While it successfully validates the firmware architecture, LoRa RF communication, and the Termux standalone SMS gateway, the hand-soldered wiring and bad joints introduce noticeable RF impedance losses (limiting range tests) and are not suited for permanent high-voltage deployment.

### 6.2 V2: Production-Grade Custom PCB Stack (In Design & Pre-Production)
To transition GridWatcher into a professional product that closely resembles a consumer device you'd find on the market, we are designing a custom dual-layer manufactured PCB stack (bypassing prototype boards entirely):

*   **Modular V-Score Separation:** The design features a physical V-score line allowing the high-voltage section to be physically snapped away and isolated from the 3.3V logic section.
*   **Bottom Board (The Power Slice):** Houses the HLK-10M05 AC-DC module, ZMPT101B active voltage sensor, MT3608 boost regulator, fuse protection, and AC prongs. Features a strict **6mm creepage clearance** between high-voltage AC mains and low-voltage DC traces for safety.
*   **Top Board (The Logic Slice):** Holds the FireBeetle 2 ESP32-C6 and features standard female expansion headers.
*   **Commercial Form Factor:** Designed to plug directly into any standard wall outlet (similar to a commercial smart plug or WiFi repeater), running off mains power with automatic fallback to an internal LiPo battery during blackouts.


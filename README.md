# Grid Watcher: system & physics dive. Rev. 3

**Author:** Kyle Mason Richter (@fuelled)  
**Hardware:** firebeetle 2 C6, ZMPT101B, HLK-10MO5, 2000mAh pouch lipo, MT3608 step up module  
**Software:** FastAPI, Scikit-learn, ESP-IDF/Arduino, termux (Android)

**Problem:** South Africa and many other countries suffer from sudden power outages due to failing and deteriorating infrastructure. There are many early warning signs that a power outage may occur such as voltage drops, frequency fluctuations, or surges.

**Solution:** That's where Grid Watcher comes to play. Its solution is not to prevent power outages but to predict them by measuring and learning these early warning signs with onboard sensors.

---

## POWER PHYSICS: AC-DC CONVERSION & PROTECTION MEASURES

### 1.1 Mains Input
The main supply of energy for this system relies on pulling power from the **230V AC (nominal) 50Hz** wall outlet. The **HLK-10M05** acts as a switched mode power supply (SMPS), using a high frequency oscillator (~70kHz) to step down 230V AC to **5V DC @ 2A** with an efficiency of ~70%.

### 1.2 Safety Design – Fuse
Because the device is plugged into the mains, a **1A 240V AC slow blow fuse** is used, sitting directly on the live wire (L) to prevent fires during shorts. The fuse physics is thermal: `I²R * t`. A 1A fuse rated for 240V limits maximum instantaneous power on the AC side to **240W** before blowout.

---

## 2. Battery & Power Architecture

### 2.1 The Battery
A **2000mAh LiPo pouch (3.7V nominal)**. It's a lightweight pouch with built‑in protection. The **Firebeetle 2** has an integrated charger and protection circuit that handles both charging and battery safety via its JST 2.0 connector.

### 2.2 Charging
From the HLK-10M05 we get **5V 2A** to feed the Firebeetle via its VCC and GND pins (the pair closest to the JST connector on the right side of the board). The on‑board charger (**TP4054**) charges the LiPo at **500 mA**. When AC power is present, the Firebeetle runs off the 5V and charges the battery. When AC fails, the Firebeetle seamlessly switches to battery power.

### 2.3.1 Current Draw (No GSM)
ESP32‑C6, Wi‑Fi, ADC sampling: ~**150 mA** average. That means the 2000mAh battery easily lasts **13+ hours** of continuous operation. Because readings are not taken when mains power is out and the board can drop into deep sleep, it can last **weeks** on battery alone.

### 2.3.2 Current Draw (On‑board GSM)
ESP32‑C6, Wi‑Fi, ADC sampling, GSM: ~**450 mA** standby average.  
GSM transmission draws short ~**2.3 A** current peaks, each lasting about **577 µs**, that repeat as needed during the SMS send. The peak‑on time depends on message length, but the average current over the transmission remains well below the peak figure.

### 2.4 3.3V–28V 1.5A – Future Proofing
On‑board, alongside the other PSU components, is an **MT3608 step‑up module** — currently not used but a work in progress. The module can output up to **28V at 1.5A** continuous and allows **2A bursts**. It is powered directly from the battery (VBAT) so it can draw the current needed for driving external LED strips, relay modules, and similar loads.

---

## 3. Signal Physics: AC Sensing (ZMPT101B & SMD Resistor Network)

To predict grid failure, we must capture the pristine, unadulterated **50Hz sine wave**. Since the **ESP32-C6** operates strictly at **3.3V logic**, the 240V AC **must** be galvanically isolated and scaled down to a safe **0V – 3.3V** range. We use the **ZMPT101B bare module** (not the amplified breakout) with a custom discrete resistor network.

### 3.1 Primary Side (High Voltage)
**Resistor:** 820kΩ (R1)  
**Math:** At 230V AC (RMS), the current limited by the primary resistor is:  
`I = V / R` → `230V / 820,000Ω ≈ 0.28mA` (RMS).  
Because it is AC, peak current is `0.28mA * √2 ≈ 0.4mA`.  
This minuscule, highly limited current entirely prevents the ZMPT101B from ever overheating or failing.

### 3.2 Secondary Side (Burden Resistor – R2)
The ZMPT101B has a turns ratio of **1:1**. The secondary coil generates this exact same 0.28mA current.  
**Burden Resistor:** 2kΩ (R2)  
**Output Voltage:** `0.28mA RMS * 2000Ω = 0.56V RMS`  
**Peak-to-Peak Voltage:** `0.56V * √2 * 2 = 1.58V` (peak-to-peak).  
This provides an excellent, large ~1.6V peak-to-peak AC wave to feed into the op-amp/ADC.

**Voltage Divider (R3 & R4):** We use two **10kΩ** resistors from the FireBeetle's 3.3V pin to Ground.  
**DC Bias Point:** `V_bias = 3.3V * (R4 / (R3 + R4)) = 3.3V * (10k / 20k) = 1.65V`.  
**Coupling Capacitor (C10):** A **1µF** non-polarized ceramic capacitor sits between the 2kΩ burden resistor and the 1.65V bias node.  
This creates a **High-Pass Filter** with a cutoff frequency:  
`f_c = 1 / (2π * R * C)`  
Using the effective resistance of the parallel 10kΩ bias resistors (5kΩ to ground) and C10:  
`f_c = 1 / (2π * 5000Ω * 0.000001F) = 31.8Hz`.  
Since the South African grid runs at 50Hz, the 50Hz wave passes through with **zero amplitude loss**, while blocking all DC signals.

**Final ADC Waveform:**  
The ESP32 ADC reads a 50Hz sine wave centered exactly at `1.65V`, oscillating between `1.65V - 0.8V = 0.85V` and `1.65V + 0.8V = 2.45V`, providing a beautiful **1.6V dynamic range** for high-resolution sampling.

### 3.3 DC Bias & AC Coupling (The "Shift")
The ESP32 ADC cannot read negative voltages. We must shift this 1.6V AC wave upward so it sits **exactly** in the middle of the 3.3V supply.

**Voltage Divider (R3 & R4):** We use two 10kΩ resistors from the FireBeetle's 3.3V pin to Ground.  
**DC Bias Point:** `V_bias = 3.3V * (R4 / (R3 + R4)) = 3.3V * (10k / 20k) = 1.65V`.  
**Coupling Capacitor (C10):** A 1µF non-polarized ceramic capacitor sits between the 2kΩ burden resistor and the 1.65V bias node.  
This creates a **High-Pass Filter** with a cutoff frequency:  
`f_c = 1 / (2π * R * C)`  
Using the effective resistance of the parallel 10kΩ bias resistors (5kΩ to ground) and C10:  
`f_c = 1 / (2π * 5000Ω * 0.000001F) = 31.8Hz`.  
Since the South African grid runs at 50Hz, the 50Hz wave passes through with zero amplitude loss, while blocking all DC signals.

**Final ADC Waveform:**  
The ESP32 ADC reads a 50Hz sine wave centered exactly at `1.65V`, oscillating between `1.65V - 0.8V = 0.85V` and `1.65V + 0.8V = 2.45V`, providing a beautiful 1.6V dynamic range for high-resolution sampling.

---

## 4. SAMPLING THEORY & FREQUENCY DETECTION ON ESP32

A simple `analogRead()` is insufficient. To detect a **49.5Hz** frequency drop (classic Eskom blackout signature), we need precise timing.

### 4.1 Nyquist-Shannon Theorem
To accurately sample a 50Hz sine wave, we must sample at **at least 100Hz**. However, to detect micro-fluctuations (grid noise), the ESP32 samples the ADC at **1,000Hz (1ms intervals)**.

### 4.2 Zero-Crossing Detection Algorithm
Because the wave is centered at 1.65V, the code implements a **Zero-Crossing Detection (ZCD)** threshold.  
The logic:
- Wait until voltage passes **above** 1.65V.
- Start a high-resolution hardware timer (`micros()`).
- Wait until the voltage passes **below** 1.65V, then passes **above** 1.65V again (completing one full positive half-cycle).
- Stop the timer (`Δt` in microseconds).

**The Frequency Formula:**  
`Frequency (Hz) = 1 / (Δt * 10^-6)`

- If `Δt` = 20,000µs (20ms) → frequency = **50.00Hz**.
- If `Δt` = 20,200µs (20.2ms) → frequency = **49.50Hz**.

This precise math allows the ESP32 to detect a **0.1Hz drop** in real-time.

---

## 5. THE MACHINE LEARNING PIPELINE (PC-HOSTED)

The ESP32 does **NOT** run the ML model locally. Instead, it streams the raw voltage/frequency values to an Android phone via a local Wi-Fi UDP broadcast. The phone forwards this data to a PC running Python.

### 5.1 Edge Relay Architecture
- **Node:** ESP32-C6.
- **Relay:** Hisense E34 Android Phone running Termux (Linux environment) with a FastAPI server listening on Port 8000.
- **Brain:** Main Windows PC. Fetches data via a `GET /get_data` endpoint from the phone.

### 5.2 Random Forest Algorithm Theory
We utilize a **Random Forest Classifier** (from `scikit-learn`). It creates **100 independent Decision Trees**. Each tree is trained on random subsets of the data, and they "vote" on the final prediction.

**The Input Features (X vector):**
1. **RMS Voltage:** (Calculated over a 1-second rolling window).
2. **Instantaneous Frequency:** (Calculated via the zero-crossing timer).
3. **Voltage Sag Gradient:** The rate of voltage drop over the last 3 seconds.
4. **Frequency Delta:** `|Target Frequency (50Hz) - Measured Frequency|`.

**The Output Label (y vector):**
- **0:** Stable (Normal 50Hz operation).
- **1:** Pre-Outage (Voltage drops below 190V OR Frequency drops below 49.4Hz for >1 second).

The model learns the non-linear relationships between these features and flags a **"Pre-Outage"** condition roughly **20 to 60 seconds** before the breaker physically trips.

---

## 6. MODULAR PCB STACK ENGINEERING

To eliminate the need for a $220 factory assembly, the final PCB design is a **two-board, break-apart modular stack**.

### 6.1 Bottom Board (The Power Slice)
- **High Voltage Isolation:** Explicit **6mm creepage distance** (separation) between AC Live/Neutral traces and the DC low-voltage traces.
- **Components:** ZMPT101B, HLK-10M05 AC-DC module, MT3608 boost module, Fuse, and Screw Terminal.
- **Physical Design:** Contains the heavy power transformers to keep parasitic noise away from the ESP32.

### 6.2 Top Board (The Logic Slice)
- **Components:** FireBeetle 2 ESP32-C6 and its BMS (built-in).
- **I/O Expansion:** The board utilizes standard **2.54mm female headers**, allowing an expansion "Hat" (such as a 5V Relay module or IR blaster) to be stacked directly on top using male header pins.
- **High-Speed Data Lines:** The SPI/I2C pins are routed to the top headers, allowing future "M5Stack-like" accessories to be swapped without modifying the core PCB.

### 6.3 Stack Mechanics
The two boards are held together using **M2.5 brass standoffs**.  
The bottom board supplies **5V and GND** to the top board through 4-pin male/female connectors, ensuring signal integrity even during 2A GSM power bursts. When manufacturing, the board is cut using **V-score** (pre-scored slits), allowing the user to physically break it into two separate, isolated boards.

---

## 7. FUTURE EXTREME UPGRADES

**Self-Improving OTA:**  
PC automatically retrains the Random Forest model weekly using new grid data. The new `model.joblib` file is `scp`'d back to the phone's Termux server. The ESP32 polls the server, downloads the new binary firmware, and flashes itself via **HTTP OTA** without being unplugged from the wall.

**IR Blaster Integration:**  
The FireBeetle 2 has a built-in IR transmitter. We will map power-outages to a specific IR code. The ESP32 can blast a "Shutdown" code to an old 5.1 surround sound receiver or air conditioner, preventing electrical surges when the power unexpectedly returns.
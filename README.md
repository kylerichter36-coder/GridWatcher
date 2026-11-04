# GridWatcher

![Status](https://img.shields.io/badge/status-v0.2%20Prototype%20%2F%20v0.3%20Integrated%20PCBA-brightgreen)
![Hardware](https://img.shields.io/badge/hardware-ESP32--S3%20%7C%20A7670E%20LTE%20%7C%20BL0939-blue)
![ML](https://img.shields.io/badge/ML-Scikit--Learn%20Random%20Forest-orange)
![License](https://img.shields.io/badge/license-MIT-green)

> Real-time electrical grid telemetry and anomaly detection system designed to measure AC line fluctuations, predict local power interruptions, and transmit alerts over cellular and LoRa networks.

---

## System Overview & Objectives
South Africa's electrical distribution grid experiences chronic load shedding, feeder trips, and voltage sags that disrupt electronics and industrial loads. Most commercial monitors are purely reactive meters that report power failure after utility service has already collapsed. GridWatcher samples AC line parameters continuously to classify grid states, log micro-fluctuations, and detect decay patterns prior to total interruption.

The project encompasses two hardware revisions:
* **Hardware v0.2:** Modular benchtop prototype built with an ESP32-C6 carrier board, SX1262 LoRa link, analog ZMPT101B module, and a handheld ST7789 TFT receiver.
* **Hardware v0.3 ("GriDwatcher china"):** Monolithic 2-layer SMT printed circuit board assembly integrating discrete compute, 4G LTE Cat-1 cellular telemetry, dual-channel energy metering, dynamic power-path battery management, and 1GB SD-NAND flash storage.

---

## Hardware Revision Architecture

```
Hardware v0.2 (Modular Prototype)
[AC Line] --> [ZMPT101B ADC] ---------> [ESP32-C6] ---> [SX1262 LoRa] ---> [Handheld / Server]
[Mains 5V] -> [MT3608 Boost / TP4056] -> [1S LiPo]

Hardware v0.3 (Monolithic SMT PCBA)
[Mains 230V] --> [HLK-10M05 5V] ------> [BQ24074 PMIC] ---> [SY8089 3.3V] ---> [ESP32-S3 Core]
[Mains 230V] --> [BL0939 Dual Meter] -> [UART 3.3V] ----------> [ESP32-S3 Core]
[1S LiPo] -----> [MAX17048 Fuel Gauge] -> [I2C] -------------> [ESP32-S3 Core]
[ESP32-S3 Core] --> [1-bit SDMMC] ----> [XTX 1GB SD-NAND]
[ESP32-S3 Core] --> [TXS0102 Level Shift] -> [A7670E 4G LTE] -> [On-PCB RF Antenna]
```

### Architectural Comparison: v0.2 vs. v0.3

| Subsystem | Hardware v0.2 (Prototype) | Hardware v0.3 ("GriDwatcher china") |
| :--- | :--- | :--- |
| **Compute Core** | DFRobot ESP32-C6 breakout board | ESP32-S3-WROOM-1-N16R8 (16MB Flash, 8MB Octal PSRAM) |
| **Energy Metering** | ZMPT101B analog transformer + MCU ADC | Belling BL0939 dual-channel energy IC (true RMS, frequency, PF) via UART |
| **Primary Telemetry** | Semtech SX1262 LoRa transceiver (868 MHz) | SIMCom A7670E-LASE 4G LTE Cat-1 cellular modem + Nano-SIM socket |
| **RF Interface** | External SMA whip antenna pigtail | Monolithic etched copper trace antenna + PI-matching filter |
| **Power Supply** | External Hi-Link module + discrete MT3608 boost | Hi-Link HLK-10M05 10W isolated SMPS + CLC PI-filter (470uF/10uH/100uF) |
| **Battery Management** | Standalone TP4056 linear charging board | TI BQ24074 dynamic power-path manager (1.0A charge, 1.55A input limit) |
| **System Step-Down** | Linear LDO on MCU breakout | Silergy SY8089A1AAC 2A synchronous buck regulator (1.5MHz, 95% efficiency) |
| **Fuel Gauge** | Raw ADC voltage divider | Maxim MAX17048 I2C fuel gauge (1% SoC resolution, alert interrupt) |
| **Local Storage** | Microcontroller internal flash only | XTX XTSDG08GWSIGA 1GB industrial SD-NAND (LGA-8) via SDMMC bus |
| **Host Programming** | Exposed USB-C connector on breakout | 4-pad flush gold Pogo-pin jig (VBUS, GND, D+, D-) with SS14 isolation diode |
| **Construction** | Perfboard, pin headers, flying leads | Monolithic 113.40 x 69.22 mm 2-layer SMT PCBA (JLCPCB assembly) |

---

## Subsystem Details

### 1. Hardware v0.3 PCBA (Manufacturing Ready)
Production files, schematics, and mechanical models are maintained in `Hardware/GridWatcher_v0.3/`:
* **Mains Input & Power Conversion:** AC input protected by a 1A slow-blow fuse and 10D471K metal-oxide varistor. Step-down conversion handled by a Hi-Link HLK-10M05 10W isolated SMPS feeding a CLC PI-filter to attenuate 5V ripple before the battery charger.
* **Power-Path PMIC & Buck Regulator:** Texas Instruments BQ24074 powers system rails directly from input power while managing single-cell Li-ion charging. If input power collapses, the PMIC switches the `VSYS` rail to battery power with zero drop-out. A Silergy SY8089 buck converter steps `VSYS` down to 3.3V for digital logic.
* **Energy Front-End:** Shanghai Belling BL0939 dual-channel energy measurement IC interfaces to mains voltage through a ZMPT101K potential transformer and dual 412k 0.1% 1206 resistor divider. Computes true RMS voltage, current, active power, and line frequency on hardware registers, read by the ESP32-S3 over UART.
* **4G LTE Cellular Subsystem:** SIMCom A7670E Cat-1 module wired to a hinged Nano-SIM socket (`J2`). Baseband 1.8V UART lines translate to 3.3V logic through a TI TXS0102 bidirectional level shifter. A 470uF low-ESR tantalum reservoir capacitor (`C19`) suppresses voltage drop during 2A cellular transmit bursts. ESP32 GPIOs control power and reset through discrete BSS138 N-channel MOSFETs.
* **Continuous Event Storage:** 1GB SD-NAND (`XTSDG08GWSIGA`, LGA-8) on an SDMMC bus stores high-resolution electrical waveforms and diagnostic logs directly on solid-state media.
* **Programming Interface:** Eliminates external USB receptacles. 4 gold test pads mate with an external pogo-pin programming fixture. An on-board SS14 Schottky diode prevents 5V back-feeding into host programming ports during live AC testing.

### 2. Hardware v0.2 Prototype
The functional prototype validates firmware logic, telemetry schemas, and predictive algorithms:
* **Edge Transmitter:** ESP32-C6 reading ZMPT101B analog waveform data, executing Layer 1 deterministic rules, and packing telemetry into binary packets.
* **Telemetry Protocol:** 12-byte packed binary format (`GridPacket`) with sync magic `0x4757`, achieving a 2.8x reduction over ASCII payloads.
* **Handheld Receiver:** ESP32-C6 dashboard paired with an ST7789 240x135 SPI TFT display showing voltage, frequency, battery percentage, and signal metrics.
* **Server Gateway:** Orange Pi / Armbian server logging telemetry datasets to CSV, publishing metrics to MQTT (Home Assistant), and driving SMS notifications via Android Termux ADB bridge.

---

## Software & Machine Learning Pipeline

```
[Mains Voltage / Frequency]
        |
        v
[Layer 1: Deterministic State Machine]
  - Normal (210V <= V <= 250V, 49.5Hz <= F <= 50.5Hz)
  - Brownout Sag (180V <= V < 210V)
  - Voltage Surge (V > 250V)
  - Frequency Jitter (F < 49.5Hz or F > 50.5Hz)
  - Blackout (V < 180V or F < 45.0Hz)
        |
        v
[Layer 2: Random Forest Anomaly Classifier]
  - Inputs: V, F, dV/dt (10s), dF/dt (10s), V_std (30s), F_std (30s), V_slope (30s), RSRP
  - Model: 3 decision trees (max_depth=4) compiled to C++ in grid_model.h
  - Output: 0-100% pre-outage risk index over a 0-30 second forward horizon
```

### Feature Mechanics & Preprocessing
* `voltage`: Instantaneous RMS line voltage.
* `frequency`: Instantaneous AC line frequency derived from zero-crossing intervals.
* `dV_dt_10s`: 10-second first-order difference in voltage ($V/s$).
* `dF_dt_10s`: 10-second first-order difference in line frequency ($Hz/s$).
* `v_std_30s`: Standard deviation of voltage over a 30-second rolling window.
* `f_std_30s`: Standard deviation of frequency over a 30-second rolling window.
* `v_slope_30s`: Linear regression slope of voltage over a 30-second window.
* `cell_signal`: Cellular tower RSRP (dBm), serving as an auxiliary indicator of regional feeder distress during wide-area power degradation.

The Python trainer (`windows_trainer/gridwatcher_ml_gui.py`) validates timestamp intervals, rejects sample windows spanning data gaps ($\Delta t > 35\text{s}$), performs an 80/20 chronological holdout split, and exports decision trees directly to native C++ functions.

---

## Repository Structure

```
GridWatcher/
├── Hardware/
│   ├── GridWatcher_v0.3/             # Monolithic SMT PCBA design
│   │   ├── GriDwatcher china.kicad_pcb  # KiCad PCB layout (113.4 x 69.2 mm)
│   │   ├── GriDwatcher china.kicad_sch  # 10-block functional schematic
│   │   ├── GriDwatcher_china_gerbers.zip# Production RS-274X Gerbers and drill files
│   │   ├── GriDwatcher_china_v0.3.step  # Full board 3D mechanical assembly
│   │   ├── jlcpcb_bom.csv            # SMT pick-and-place Bill of Materials
│   │   ├── jlcpcb_bom_complete.csv   # Complete BOM including hand-assembled THT
│   │   ├── jlcpcb_cpl.csv            # Centroid placement file with feeder rotation offsets
│   │   └── README.md                 # v0.3 technical specs, pin mapping, and parts errata
│   └── monitoring v0.2/              # Legacy v0.2 carrier board schematics and Gerbers
├── home_sender/                      # ESP32 base station firmware
│   ├── home_sender.ino               # AC sampling, Layer 1 classification, LoRa/cellular TX
│   ├── grid_model.h                  # Compiled Random Forest decision tree model
│   └── secrets.h.example             # Network credential configuration template
├── gridwatcher_dashboard2/           # Handheld receiver firmware (ESP32-C6 + ST7789 TFT)
├── phone_server/                     # Cellular and SMS gateway scripts (Termux / ADB)
├── windows_trainer/                  # Training pipeline, PyQt GUI, and firmware flash tool
│   ├── gridwatcher_ml_gui.py         # Rolling feature extraction, tree training, C++ exporter
│   └── install_startup.bat           # Environment bootstrapper for arduino-cli and toolchains
├── JOURNAL.md                        # Engineering build journal and hardware progression log
├── version.json                      # Firmware and model tracking manifest
└── README.md
```

---

## Build and Setup Instructions

### Hardware Manufacturing (v0.3)
1. Download `Hardware/GridWatcher_v0.3/GriDwatcher_china_gerbers.zip`.
2. Upload to JLCPCB (2-layer FR-4, 1.6mm thickness, 1oz copper, green solder mask, white silkscreen).
3. Select SMT assembly (top side only), supplying `jlcpcb_bom.csv` and `jlcpcb_cpl.csv`.
4. Hand-assemble remaining through-hole components post-fabrication: Hi-Link HLK-10M05 (`U1`), ZMPT101K transformer (`TR1`), 10D471K varistor (`RV1`), 5x20mm fuse clips (`F1`), and 2-pin JST-PH battery header (`J1`).

### Toolchain & Firmware Setup
1. Run `windows_trainer/install_startup.bat` to set up `arduino-cli`, the ESP32 platform core, and required libraries (`RadioLib`, `Adafruit-GFX-Library`, `Adafruit_ST7789`, `Adafruit_BusIO`).
2. Configure Wi-Fi or cellular APN credentials in `home_sender/secrets.h`.
3. Compile and flash the target firmware:
   ```bash
   arduino-cli compile --fqbn esp32:esp32:esp32s3 home_sender
   arduino-cli upload -p <PORT> --fqbn esp32:esp32:esp32s3 home_sender
   ```
4. Run `python windows_trainer/gridwatcher_ml_gui.py` to retrain decision trees from newly collected CSV telemetry.

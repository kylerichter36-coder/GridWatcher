# GridWatcher: Engineering Build Journal
**Project:** GridWatcher (Hardware v0.3 / "GriDwatcher china")  
**Author:** Kyle Mason Richter (`@fuelled` / `kylerichter36-coder`)  
**Target:** Hack Club Fallen: Maker Faire Shenzhen (Dec 11–14, 2026)  
**Hardware Repository:** `https://github.com/kylerichter36-coder/GridWatcher.git`

---

## Mission & System Rationale
South Africa's electrical grid suffers from rolling load shedding, localized distribution decay, and sudden circuit breaker trips. GridWatcher measures AC line parameters to detect grid instability before total power loss occurs, analyzing line frequency decay, voltage sag slopes, and harmonic jitter.

For Hack Club Fallen, the hardware transitions from modular breakout boards and protoboard point-to-point wiring to an integrated 2-layer SMT printed circuit board assembly. External USB sockets, breadboard jumpers, loose breakout modules, and external antenna pigtails are eliminated in favor of discrete ICs, an integrated Li-ion power path, on-board cellular baseband, and solid-state flash on a single board.

---

## Build Log: November 3, 2026

### Session Objectives
1. Finalize ESP32-S3 compute core and external programming interface.
2. Embed industrial solid-state flash storage (SD-NAND).
3. Design 4G LTE Cat-1 cellular subsystem with level translation and FET control.
4. Integrate monolithic on-board etched trace antenna.
5. Complete schematic routing across all 10 modular functional blocks.

---

### 1. ESP32-S3 Core & 4-Pad Pogo-Pin Programming Interface
* **Design Constraint:** In an enclosed wall-mounted meter, external USB-C receptacles collect airborne debris, take up enclosure volume, and expose internal rails to ESD events.
* **Implementation:** The USB-C connector was removed in favor of 4 gold Pogo-pin test pads (`VBUS`, `GND`, `USB_D+`, `USB_D-`). The ESP32-S3 integrates a hardware USB-Serial-JTAG controller on silicon, enabling automatic reset into ROM bootloader mode over USB D+/D- without dedicated mechanical buttons.
* **Reverse Power & External Pad Isolation:**
  * When flashing the microcontroller via a pogo programming jig while AC line power is connected, 5V from the Hi-Link SMPS could back-feed into the host computer's USB port.
  * A low forward-drop Schottky diode (`D1`, SS14 / B5819W) was placed between the `VBUS` test pad (Anode) and the `+5VB` rail (Cathode).
  * This blocks internal 5V supply current from flowing back into the host PC. When operating from AC mains without the jig, the exposed external `VBUS` pad rests at 0V.
* **Reset Circuit Time Constant (`C16`):**
  * A 10µF capacitor was initially assigned to the ESP32 `EN` pin with a 10kΩ pull-up, resulting in a 100ms RC time constant ($\tau = R \times C$). This rise time caused auto-reset handshake failures in `esptool.py`.
  * Corrected `C16` to 1.0µF ($\tau = 10\text{ms}$) per Espressif hardware design guidelines.

---

### 2. High-Speed Power Plane Decoupling
* High-frequency supply decoupling on the 3.3V rail:
  * The smallest capacitance (100nF ceramic) is placed directly adjacent to each VDD pin, with bulk 10µF capacitors placed downstream.
  * High-frequency transient switching current ($V = L \cdot \frac{di}{dt}$) requires minimal parasitic loop inductance. Each decoupling cap grounds into the bottom plane through dedicated vias placed close to pad terminals.

---

### 3. Industrial Solid-State Storage: SD-NAND (LGA-8)
* **Design Selection:** Replaced the external MicroSD card socket with an industrial SD-NAND IC (`XTSDG08GWSIGA`, LCSC `C25836657`).
* **Packaging & Reliability:** The LGA-8 ($6 \times 8\text{mm}$) package integrates an SLC/MLC NAND die and embedded controller with bad block management and hardware ECC, eliminating mechanical card chatter and contact oxidation.
* **Bus Wiring:**
  * Wired for 1-bit SDMMC bus operation on dedicated ESP32-S3 GPIOs: `IO11` (CMD), `IO12` (CLK via 22Ω damping resistor `R22`), `IO13` (DAT0), and `IO14` (CS).
  * 10kΩ pull-up resistors to `+3V3` placed on CMD, DAT0, DAT1, DAT2, and DAT3.
  * Local decoupling placed within 3.2mm of VCC pads, returning to central thermal ground.

---

### 4. 4G LTE Cat-1 Cellular Subsystem (SIMCom A7670E)
* **Modem Selection:** SIMCom A7670E-LASE (LCSC `C5362211`), supported by standard JLCPCB automated SMT assembly feeders.
* **Location Telemetry Approach:**
  * Evaluated dedicated GNSS/GPS (`FASE`) versus pure LTE (`LASE`).
  * Because GridWatcher installs indoors near electrical distribution boards where satellite signals suffer high attenuation, satellite GPS was omitted to eliminate constant satellite lock attempts and RF power consumption. Location mapping uses cellular tower ID triangulation (LBS) and fixed site metadata.
* **Power Delivery:** Powered directly from the uninterruptible `VSYS` rail (TI BQ24074 PMIC), buffered by a 470µF low-ESR tantalum capacitor (`C19`) to handle 2.0A GSM transmission current bursts without triggering modem undervoltage lockout (UVLO < 3.4V).
* **Nano-SIM Interface:** 6-pin push-pull socket (`J2`, BOOMELE `C2963104`). Grounded pin 5 and decoupled `USIM1_VDD` with a local 100nF capacitor.
* **1.8V to 3.3V Logic Level Translation:**
  * A7670E UART lines operate on a 1.8V baseband domain (2.1V absolute maximum rating).
  * Placed a Texas Instruments `TXS0102DCUR` bidirectional translator powered by modem `1V8_MODEM` and system `+3V3`, cross-wiring TX/RX between ESP32 and baseband ports.
* **Modem Control Switching:** Added dual BSS138 N-channel MOSFET low-side switches (`Q1`, `Q2`) with 10kΩ gate pull-downs, driven by ESP32 `IO16` (`ESP_PWRKEY`) and `IO15` (`ESP_RESET`).

---

### 5. Monolithic On-PCB Trace Antenna
* Replaced external whip antenna cables with an on-board copper trace radiator.
* Integrated a standard RF $\pi$-matching network (`R31` 0Ω series link + `C24`/`C25` unpopulated shunt pads to ground) adjacent to pin 60 (`RF_ANT`).
* Etched antenna trace over a ground plane keepout area on top and bottom copper layers to allow post-fabrication impedance matching.

---

## 10-Block Schematic & Subsystem Status

| Block | Subsystem | Components | Status |
| :---: | :--- | :--- | :---: |
| 1 | Mains Input & Protection | 1A Fuse, 10D471K MOV, HLK-10M05 5V SMPS, ZMPT101K Transformer | Done |
| 2 | CLC Filter & Metering | 470µF + 10µH + 100µF Pi-filter, BL0939 dual-channel energy IC | Done |
| 3 | Power-Path PMIC & Charger | TI BQ24074 (1.0A charge, 1.55A input limit), JST-PH LiPo header | Done |
| 4 | 3.3V Buck Regulator | Silergy SY8089A (2A, 1.5MHz, 2.2µH inductor) | Done |
| 5 | Battery Fuel Gauge | Maxim MAX17048 (I2C, 1% SoC resolution, alert pin) | Done |
| 6 | Compute Core | ESP32-S3-WROOM-1-N16R8, 1µF reset circuit, 100nF decoupling | Done |
| 7 | Pogo Programming Interface | 4 Gold test pads, SS14 isolation diode, 22Ω USB series resistors | Done |
| 8 | Solid-State Flash Storage | 1 GB SD-NAND (XTSDG08GWSIGA), 1-bit SDMMC, 10k pull-ups | Done |
| 9 | Cellular Modem Subsystem | SIMCom A7670E-LASE LTE Cat-1, Nano-SIM, 470µF tantalum | Done |
| 10 | Level Shift & RF Antenna | TXS0102DCUR, dual BSS138 switches, Pi-matching, trace antenna | Done |

---

## Manufacturing Pipeline Status
* **Gerber Verification:** RS-274X artwork and Excellon drill files generated (`GriDwatcher_china_gerbers.zip`). Removed stray silkscreen lines overlapping IC footprints and validated order code marking (`JLCJLCJLCJLC`).
* **BOM & Feeder Matching:** SMT BOM (`jlcpcb_bom.csv`) validated with exact LCSC part numbers. Corrected component mismatches on J2 (Nano-SIM socket), Q1/Q2 (BSS138), L1 (10µH shielded inductor), C19 (470µF tantalum), C1/C2 (aluminum electrolytic), and voltage divider precision resistors (412k 0.1%).
* **CPL Centroid Rotation Offsets:** Adjusted Pick-and-Place file (`jlcpcb_cpl.csv`) for tape-and-reel feeder orientation:
  * C2: 0° rotation (aligns cathode band with GND pad).
  * U4: 180° rotation (aligns SOT-23-5 pins 1-3 with VSYS/GND/LX pads).
* **3D CAD Assembly:** Exported STEP AP214 mechanical model (`GriDwatcher_china_v0.3.step`, 8.7MB) for enclosure modeling and tolerance verification.

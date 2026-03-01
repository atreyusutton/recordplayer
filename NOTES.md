# Digital Turntable -- Project Notes

## Parts List

### Compute & Display

| # | Part | Key Specs |
|---|------|-----------|
| 1 | Waveshare 4" HDMI Round Touch Display | 720x720 IPS, 10-point capacitive touch, HDMI + USB |
| 2 | InnoMaker HiFi DAC HAT | PCM5122, 384 kHz / 32-bit, 112 dB SNR, RCA + 3.5 mm out |

### Power

| # | Part | Key Specs |
|---|------|-----------|
| 3 | ALITOVE 12V 5A AC-DC Power Supply | 100-240V AC in, 60W, 5.5x2.5 mm barrel plug |
| 4 | DROK Buck Converter (12V to 5V) | 9-36V in, 5-6A out, USB output module |
| 5 | USB-C Male to 2-Wire Pigtail | 5V 3A, 22 AWG leads |

### Wiring & Protection

| # | Part | Key Specs |
|---|------|-----------|
| 6 | 12 AWG Inline Fuse Holder | ATC/ATO blade, using 5A fuse |
| 7 | 18 AWG 2-Conductor Red/Black Wire (40 ft) | 12V/24V DC rated, stranded |
| 8 | DC Barrel Jack Connectors (10 pack) | 5.5x2.1 mm female, screw/solder terminal |

### From the Original Record Player

| # | Part |
|---|------|
| 9 | Master on/off switch |
| 10 | Motor on/off switch |
| 11 | 33/45 RPM speed switch |

### Purchased but Not Currently Used

| Part | Reason |
|------|--------|
| Anmbest 400W Dual MOSFET Trigger Switch | Motor is hardwired to OEM switches, no Pi control needed |
| BOJACK 10SQ050 Schottky Diodes (10A / 50V) | May add reverse polarity protection later |

---

## Original Turntable Wiring (Stock Reference)

### Power
- 12V DC input feeds the stock circuit board

### Controls
- Start/Stop switch (2 wires) -> 2 prongs on 4-prong board connector
- 33/45 speed switch (2 wires) -> motor
- Motor (2 wires) -> remaining 2 prongs on 4-prong connector
- Master on/off switch (2 wires) -> circuit board

### Audio Path (Analog)
- Cartridge outputs: PH_R + ground, PH_L + ground
- Routed to RCA outputs through stock internal preamp

---

## Current Wiring

**Positive path:** Wall AC -> 12V 5A brick -> barrel connector -> master on/off switch -> 5A fuse -> splits two ways: one branch to the self-contained motor system (motor + motor on/off + 33/45 speed switch), the other into the 12V-to-5V buck converter -> USB-C pigtail -> Pi.

**Ground path:** Wall AC -> 12V 5A brick -> barrel connector -> splits to motor negative and buck converter negative -> USB-C ground.

The Pi has the DAC HAT stacked on top (RCA out). USB from Pi powers the 4" screen, micro-HDMI drives the display signal.

```
             AC WALL
                │
                ▼
        12V 5A POWER SUPPLY
                │
          Master Switch
                │
             5A Fuse
                │
     +----------+----------+
     |                     |
     ▼                     ▼
 MOTOR SYSTEM        Buck Converter
 (on/off, speed)           │
                           ▼
                        5V USB-C
                           │
                           ▼
                      Raspberry Pi
                        │      │
                        │      ▼
                        │   Round Display
                        ▼
                      DAC HAT
                        │
                        ▼
                     RCA OUT
```

---

## Future Features

### Physical Volume Knob
Rotary encoder wired to GPIO for hardware volume control. Turning the knob adjusts the ALSA mixer level on the DAC directly, no screen interaction needed. Could reuse the original turntable's tonearm area or mount near the existing switches.

### Standalone Control UI ✅ BUILT

Flask backend (`control.py`) + dark-theme HTML/JS frontend (`static/index.html`) running at **http://rasp-bumpy:8080**.

- **Backend:** Flask on port 8080, Spotify Web API OAuth (Authorization Code flow), token auto-refresh, 60s device ID cache
- **Frontend:** Dark theme (`#0a0a0a` / Spotify green `#1db954`), album art + track info, progress bar with seek, play/pause/prev/next, volume slider, scrollable playlist browser
- **Auth:** One-time SSH tunnel setup (`ssh -L 8080:localhost:8080 rasp-bumpy`) then open `http://localhost:8080` on Mac; thereafter browse directly at `http://rasp-bumpy:8080`
- **Credentials:** `config.json` (gitignored), Redirect URI = `http://127.0.0.1:8080/callback`
- **Target display size:** 500×282px (3.5" 16:9 — for future dedicated screen)

#### Next: Physical Screen
Add a 3.5" rectangular display (480×320 or 800×480) to Pi HDMI 1 in Chromium kiosk mode:
```
HDMI 0 -> Round 720x720 (album art, spinning)
HDMI 1 -> Rectangular 500x282 (control UI)
```

### Other Ideas
- Physical volume knob (rotary encoder on GPIO → ALSA mixer)
- Physical play/pause button wired to GPIO
- Voice search (possible but complex)

# Digital Turntable

A 1byone vinyl record player retrofitted with a Raspberry Pi 4 to become a self-contained Spotify Connect streaming turntable. The original motor and platter still spin real vinyl, while a Waveshare 4" round display mounted in the center shows the current album art rotating at 33 1/3 RPM.

## How It Works

```
Spotify (phone/desktop/etc.)
        │  Spotify Connect
        ▼
   Raspotify (librespot)
        │
        ├──→ DAC HAT ──→ RCA OUT ──→ Speakers
        │
        ▼
   onevent.sh (track metadata → /tmp/now_playing.json)
        │
        ▼
   display.py (spinning album art on round LCD)
```

1. **Raspotify** runs as a systemd service, making the Pi a Spotify Connect device named "Record Player". Select it from any Spotify app to stream.
2. When a track changes or playback state updates, librespot fires **`onevent.sh`**, which writes the track title, artist, and cover art URL to `/tmp/now_playing.json`.
3. **`display.py`** (also a systemd service) polls that JSON file, downloads the cover art, and renders it as a spinning record on the 720x720 round display using pygame. Art crossfades smoothly between tracks.

## Hardware

### Compute & Display

| Part | Details |
|------|---------|
| Raspberry Pi 4 (8 GB) | Runs Raspberry Pi OS with Wayland |
| Waveshare 4" Round HDMI LCD | 720x720 IPS, capacitive touch, HDMI + USB |
| InnoMaker HiFi DAC HAT | PCM5122, 384 kHz/32-bit, RCA + 3.5 mm out |

### Power

| Part | Details |
|------|---------|
| ALITOVE 12V 5A AC-DC Supply | 100-240V AC in, 5.5x2.5 mm barrel out |
| DROK Buck Converter 12V-to-5V | Powers the Pi via USB-C pigtail |
| 12 AWG Inline Fuse Holder | 5A blade fuse for branch protection |
| 18 AWG Red/Black Wire | 12V DC wiring between modules |
| DC Barrel Jack Connectors | 5.5x2.1 mm, modular 12V connections |
| USB-C Male to 2-Wire Pigtail | 5V 3A, custom power cable to Pi |

### From the Original Record Player

- Master on/off switch
- Motor on/off switch
- 33/45 RPM speed switch
- Turntable motor (hardwired to the 12V rail, independent of the Pi)

### Wiring

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

The motor system is completely independent from the Pi -- the OEM switches control it directly off the 12V rail.

## Setup

### 1. Install Raspotify and configure the DAC

```bash
./setup.sh
```

This installs the `hifiberry-dacplus` overlay, installs Raspotify, and configures it for the PCM5122 DAC at 320 kbps. A reboot is required if the overlay was just added.

### 2. Deploy the display

From your development machine:

```bash
./deploy-display.sh recordplayer.local
```

Or directly on the Pi:

```bash
sudo ./deploy-display.sh --local
```

This installs Python dependencies (`pygame`, `pillow`), copies the app files to `/home/admin/apps/recordplayer/`, installs the `record-display.service` systemd unit, patches `LIBRESPOT_ONEVENT` into the Raspotify config, and restarts both services.

### 3. Play music

Open Spotify on any device, tap the Connect icon, and select **Record Player**.

## Files

| File | Purpose |
|------|---------|
| `setup.sh` | Installs Raspotify and configures the DAC HAT |
| `display.py` | Spinning album art display (pygame, runs as systemd service) |
| `onevent.sh` | librespot event hook -- writes now-playing metadata to JSON |
| `deploy-display.sh` | Deploys display app to the Pi (remote via rsync or local) |
| `record-display.service` | systemd unit for the display |
| `diagnose-audio.sh` | Audio troubleshooting script |
| `NOTES.md` | Parts list, original wiring reference, and future plans |

## Troubleshooting

Run the diagnostic script on the Pi:

```bash
bash diagnose-audio.sh
```

It checks the DAC overlay, ALSA devices, Raspotify config, and can play a test tone. Common fixes:

- **No audio after reboot** -- Verify the DAC shows up in `aplay -l`, check that `LIBRESPOT_DEVICE` in `/etc/raspotify/conf` matches
- **Display not starting** -- Check `sudo systemctl status record-display` and `sudo journalctl -u record-display -f`
- **Album art not updating** -- Verify `LIBRESPOT_ONEVENT` is set in `/etc/raspotify/conf` and that `/tmp/now_playing.json` is being written

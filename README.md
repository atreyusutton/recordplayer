# Digital Turntable

A 1byone vinyl record player retrofitted with a Raspberry Pi 4 to become a self-contained Spotify Connect streaming turntable. The original motor and platter still spin real vinyl, while a Waveshare 4" round display mounted in the center shows the current album art rotating at 33⅓ RPM. A web-based control UI lets you browse playlists, control playback, and adjust volume from any browser on the network — no phone required.

## How It Works

```
Spotify (phone/desktop/etc.)    ←──────────────────────────────────┐
        │  Spotify Connect                                          │
        ▼                                                           │
   Raspotify (librespot)                                  control.py (Flask :8080)
        │                                                           │
        ├──→ DAC HAT ──→ RCA OUT ──→ Speakers              Spotify Web API
        │
        ▼
   onevent.sh (track metadata → /tmp/now_playing.json)
        │
        ▼
   display.py (spinning album art on round LCD)
```

1. **Raspotify** runs as a systemd service, making the Pi a Spotify Connect device named "Record Player". Select it from any Spotify app to stream.
2. When a track changes, librespot fires **`onevent.sh`**, which writes track title, artist, and cover art URL to `/tmp/now_playing.json`.
3. **`display.py`** polls that JSON file, downloads the cover art, and renders it as a continuously spinning record on the 720×720 round display using pygame. Art crossfades smoothly between tracks.
4. **`control.py`** serves a dark-themed web UI at port 8080 for browsing playlists, controlling playback, seeking, and adjusting volume — designed for touch and eventually a dedicated second display.

## Hardware

### Compute & Display

| Part | Details |
|------|---------|
| Raspberry Pi 4 (8 GB) | Runs Raspberry Pi OS Bookworm with Wayland |
| Waveshare 4" Round HDMI LCD | 720×720 IPS, capacitive touch, HDMI + USB |
| InnoMaker HiFi DAC HAT | PCM5122, 384 kHz/32-bit, RCA + 3.5 mm out |

### Power

| Part | Details |
|------|---------|
| ALITOVE 12V 5A AC-DC Supply | 100-240V AC in, 5.5×2.5 mm barrel out |
| DROK Buck Converter 12V-to-5V | Powers the Pi via USB-C pigtail |
| 12 AWG Inline Fuse Holder | 5A blade fuse for branch protection |
| 18 AWG Red/Black Wire | 12V DC wiring between modules |
| DC Barrel Jack Connectors | 5.5×2.1 mm, modular 12V connections |
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

The motor system is completely independent from the Pi — the OEM switches control it directly off the 12V rail.

## Setup

### 1. Install Raspotify and configure the DAC

```bash
./setup.sh
```

Installs the `hifiberry-dacplus` overlay, installs Raspotify, and configures it for the PCM5122 DAC at 320 kbps. A reboot is required if the overlay was just added.

### 2. Deploy

Push to the Pi's git remote (auto-deploys via post-receive hook):

```bash
git push
```

Or run the deploy script directly on the Pi:

```bash
sudo ./deploy-display.sh --local
```

This installs Python dependencies, copies app files to `/home/admin/apps/recordplayer/`, installs systemd units, and restarts services.

### 3. Connect Spotify (control UI — one time only)

Create a Spotify Developer App at [developer.spotify.com](https://developer.spotify.com/dashboard) and add `http://127.0.0.1:8080/callback` as a Redirect URI. Write credentials to the Pi:

```bash
ssh rasp-bumpy "cat > /home/admin/apps/recordplayer/config.json << 'EOF'
{\"client_id\": \"YOUR_ID\", \"client_secret\": \"YOUR_SECRET\"}
EOF"
```

Then open an SSH tunnel to do the one-time login:

```bash
ssh -L 8080:localhost:8080 rasp-bumpy   # keep open
# Open http://localhost:8080 → click Connect Spotify → log in
# After login, close the tunnel
```

From then on, access the control UI at **`http://rasp-bumpy:8080`** from any browser on the network.

### 4. Play music

Open Spotify on any device, tap the Connect icon, and select **Record Player**. Or use the control UI to browse and play directly.

## Files

| File | Purpose |
|------|---------|
| `setup.sh` | Installs Raspotify and configures the DAC HAT |
| `display.py` | Spinning album art display (pygame, systemd service) |
| `onevent.sh` | librespot event hook — writes now-playing metadata to JSON |
| `control.py` | Spotify control UI backend (Flask, port 8080, systemd service) |
| `static/index.html` | Control UI frontend (dark theme, touch-friendly) |
| `deploy-display.sh` | Deploys all app files to the Pi |
| `record-display.service` | systemd unit for the display |
| `control.service` | systemd unit for the control UI |
| `diagnose-audio.sh` | Audio troubleshooting script |
| `NOTES.md` | Parts list, wiring reference, and future plans |

## Troubleshooting

**Display not starting:**
```bash
sudo systemctl status record-display
sudo journalctl -u record-display -f
```

**Control UI not starting:**
```bash
sudo systemctl status control
sudo journalctl -u control -f
```

**Album art not updating:**
```bash
cat /tmp/onevent_debug.log     # see exactly what librespot sent
cat /tmp/now_playing.json      # see what display.py is reading
sudo systemctl status raspotify
```

**No audio after reboot:**
```bash
bash diagnose-audio.sh
```
Verifies DAC overlay, ALSA device name, Raspotify config, and plays a test tone.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A retrofitted vinyl turntable with a Raspberry Pi 4 acting as a Spotify Connect device. The original motor/platter spin is controlled via a MOSFET on GPIO18. A Waveshare 4" round 720×720 HDMI display shows album art rotating at 33⅓ RPM. A 3.5" rectangular touchscreen runs a Chromium kiosk with the Spotify control UI. Audio output via Focusrite Scarlett Solo 4th Gen (USB). Two rotary encoders provide physical volume and navigation control.

## Deployment

This is a Pi-only runtime project — no local build steps or test suites. All code runs on the Pi.

**Standard deploy (from dev machine — git push auto-deploys):**
```bash
git push   # Pi's post-receive hook deploys to /home/admin/apps/recordplayer/
```

**After pushing, restart services if needed:**
```bash
ssh rasp-bumpy "sudo systemctl restart record-display control knob nav-knob"
ssh rasp-bumpy "sudo systemctl restart raspotify"  # if audio config changed
```

**IMPORTANT — onevent.sh sync:** Raspotify calls `/usr/local/bin/onevent-recordplayer.sh`, not the repo's copy. After any change to `onevent.sh`:
```bash
ssh rasp-bumpy "sudo cp /home/admin/apps/recordplayer/onevent.sh /usr/local/bin/onevent-recordplayer.sh && sudo systemctl restart raspotify"
```

**IMPORTANT — raspotify device override:** The systemd override at `/etc/systemd/system/raspotify.service.d/onevent.conf` hardcodes `--device` and `--format` on the ExecStart line. Changes to `/etc/raspotify/conf` alone won't take effect — you must also update the override:
```bash
ssh rasp-bumpy "sudo cat /etc/systemd/system/raspotify.service.d/onevent.conf"
```

**Check status on Pi:**
```bash
ssh rasp-bumpy "sudo systemctl status raspotify record-display control knob nav-knob"
ssh rasp-bumpy "sudo journalctl -u record-display -f"
ssh rasp-bumpy "sudo journalctl -u control -f"
ssh rasp-bumpy "cat /tmp/now_playing.json"
```

**Audio troubleshooting:**
```bash
ssh rasp-bumpy "bash /home/admin/apps/recordplayer/diagnose-audio.sh"
ssh rasp-bumpy "aplay -l"   # verify Scarlett is detected
ssh rasp-bumpy "lsusb | grep Focusrite"  # verify USB connection
```

**Debug album art issues:**
```bash
ssh rasp-bumpy "cat /tmp/onevent_debug.log"   # logs every librespot event
ssh rasp-bumpy "cat /tmp/now_playing_state.json"
```

## Architecture

```
Spotify app  ──Spotify Connect──▶  raspotify (librespot)  ──▶  Scarlett Solo (USB)  ──▶  KRK Rokit 5s
                                          │
                              /usr/local/bin/onevent-recordplayer.sh
                                          │
                                 /tmp/now_playing.json
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
             display.py              control.py            onevent.sh
          (polls file 1s +        (Flask :8080)         (writes wake file)
           polls API 3s)               │
                │               ┌──────┼──────┐
                ▼               ▼      ▼      ▼
         pygame Wayland      Chromium  knob   nav-knob
         HDMI-A-1 (round)    DSI-1     poll   poll
                             (touch)

IPC files:
  /tmp/now_playing.json       — librespot track events
  /tmp/now_playing_state.json — persisted track info for resume
  /tmp/recordplayer_sleep     — sleep state flag
  /tmp/recordplayer_wake      — wake trigger (touch clears it)
  /tmp/recordplayer_volume    — current volume (written by knob.py)
  /tmp/recordplayer_nav       — nav events (written by nav-knob.py)
```

## Key files

| File | Pi path | Purpose |
|------|---------|---------|
| `display.py` | `/home/admin/apps/recordplayer/display.py` | Spinning album art display (polls local file + Spotify API) |
| `onevent.sh` | `/home/admin/apps/recordplayer/onevent.sh` + `/usr/local/bin/onevent-recordplayer.sh` | librespot event hook + wake trigger |
| `control.py` | `/home/admin/apps/recordplayer/control.py` | Flask Spotify control backend + knob poll endpoint |
| `static/index.html` | `/home/admin/apps/recordplayer/static/index.html` | Control UI frontend |
| `knob.py` | `/home/admin/apps/recordplayer/knob.py` | Volume knob — GPIO → ALSA mixer + file IPC |
| `nav-knob.py` | `/home/admin/apps/recordplayer/nav-knob.py` | Nav knob — GPIO → file IPC (bypasses Wayland focus) |
| `config.json` | `/home/admin/apps/recordplayer/config.json` | Spotify credentials — **gitignored, Pi only** |
| `tokens.json` | `/home/admin/apps/recordplayer/tokens.json` | OAuth tokens — **gitignored, Pi only** |
| `setup.sh` | — | Raspotify + Scarlett audio setup |
| `diagnose-audio.sh` | — | Audio troubleshooting |

## GPIO Pinout

```
VOLUME KNOB (knob.py)       NAV KNOB (nav-knob.py)     MOSFET (motor)
─────────────────────       ──────────────────────      ──────────────
+   → pin 17 (3.3V)        +   → pin 1  (3.3V)        SIG → pin 12 (GPIO18)
GND → pin 20 (GND)         GND → pin 9  (GND)         GND → pin 14 (GND)
CLK → pin 16 (GPIO23)      CLK → pin 11 (GPIO17)
DT  → pin 18 (GPIO24)      DT  → pin 13 (GPIO27)
SW  → pin 22 (GPIO25)      SW  → pin 15 (GPIO22)
```

## IPC: `/tmp/now_playing.json`

`onevent.sh` is the librespot `--onevent` hook. Written via `python3 json.dumps()` to handle multi-artist newline separators.

Events handled:
- `track_changed` — writes full JSON + persists to state file + writes wake trigger
- `playing` — restores from state file + writes wake trigger
- `paused` / `stopped` — writes minimal event JSON

`flock` serializes concurrent invocations.

## Sleep/Wake System

**Sleep:** After 2 minutes of no active playback on any Spotify device, both screens blank via `vcgencmd display_power 0`. API polling stops. Raspotify stays running and discoverable.

**Wake triggers** (all write `/tmp/recordplayer_wake`):
- Volume knob turn or press
- Nav knob turn or press
- Touchscreen tap (UI calls `POST /api/wake`)
- Spotify Connect transfer (onevent.sh fires on `playing`/`track_changed`)

**On boot:** Black screen until first track plays — no "Waiting for Spotify" text.

**Persistence:** Last album art and track info persist on screen after switching to another device, until sleep triggers.

## display.py rendering pipeline

1. **Poll local** — `PlayerState.poll()` checks `/tmp/now_playing.json` mtime every 1s; only reacts to `"playing"` events
2. **Poll API** — background thread polls `http://localhost:8080/api/now-playing` every 3s for art from any Spotify device
3. **Async load** — background thread download via `requests.Session`; URL-keyed cache (5 entries); one retry
4. **Cross-fade** — 0.5s linear alpha blend on track change
5. **Rotation** — always spins at 33⅓ RPM; **clockwise** (angle subtracted — pygame CCW for positive)
6. **Render** — 60 FPS; black when no cover loaded

## Audio: Focusrite Scarlett Solo 4th Gen

- ALSA card: `Gen`
- Device: `hw:Gen` with `--format S32` (native 24-bit; S16 not supported on hw: directly, `plughw:Gen` works but degrades quality)
- Volume controls: `Mix A Input 01` (L) + `Mix B Input 02` (R) — both set together
- Volume: 22 steps of 4%, range 0–88% (88% ≈ 0dB, above clips)
- Boot volume: 48% (12 clicks)
- Physical loudness: Scarlett's monitor knob → KRK Rokit 5 monitors

**USB power:** The round display is powered separately from the 12V→5V buck converter (power terminals), with only USB data lines to the Pi. This frees the Pi's USB power budget for the Scarlett. Without this, the Scarlett drops off USB.

## Knob IPC (bypasses Wayland)

Both knobs use **file IPC** instead of uinput/evdev because Wayland keyboard events only go to the focused window (Chromium vs pygame focus conflict).

- `knob.py` writes volume to `/tmp/recordplayer_volume` **before** running amixer (in background thread) for instant UI feedback
- `nav-knob.py` writes nav events to `/tmp/recordplayer_nav`
- `control.py` serves `GET /api/knob-poll` — reads both files, returns `{volume, nav}`
- UI polls `/api/knob-poll` every 100ms

## control.py (Spotify Control UI)

Flask backend on port 8080. Credentials in `config.json` (gitignored). Tokens auto-refresh.

**Endpoints:**
- `GET /` — serves `static/index.html`
- `GET /login` → `GET /callback` — OAuth Authorization Code flow
- `GET /api/now-playing` — current playback state
- `POST /api/play|pause|next|previous|seek|volume` — playback commands
- `POST /api/shuffle` — `{state: bool}`
- `POST /api/repeat` — `{state: "off"|"track"|"context"}`
- `GET /api/playlists` — user's own playlists only (filtered by owner.id == user_id)
- `POST /api/play-playlist` — `{playlist_id}`
- `GET /api/playlist/<id>/tracks` — uses `/playlists/{id}/items` (NOT /tracks — 403)
- `POST /api/play-track` — `{track_uri, playlist_uri?, offset?}`
- `POST /api/play-context` — `{context_uri, offset?}`
- `GET /api/liked-tracks` — `{tracks[], total, collection_uri}`
- `POST /api/play-liked` — plays liked songs collection
- `GET /api/search` — `?q=...`; returns `{tracks[], albums[]}`
- `GET /api/recently-played` — deduplicated by album; up to 6 items
- `GET /api/knob-poll` — fast volume + nav state (100ms polling)
- `GET /api/volume-level` — volume from file (fallback)
- `POST /api/wake` — touchscreen wake trigger
- `GET /api/sleep-status` — `{sleeping: bool}`

**Caches:**
- `_device_cache`: "Record Player" device ID, 60s TTL
- `_user_id_cache`: Spotify user ID from `/me`, 1hr TTL

**Audio monitor thread** (daemon):
- Polls every 15s; skips during sleep
- Auto-pauses if ALSA PCM silent for 60s while Spotify reports playing

## Display Layout

```
HDMI-A-1 at (0,0): 720×720 round display (album art, pygame)
DSI-1 at (720,120): 800×480 touchscreen (control UI, Chromium kiosk)
```

Set in `~/.config/labwc/autostart` via `wlr-randr` (overrides `labwc-outputs.xml`).

## Pi environment

- OS: Raspberry Pi OS Bookworm, Wayland (labwc compositor)
- Python: 3.13.5, pygame 2.6.1, Pillow 11.1.0, requests, flask
- Audio: Focusrite Scarlett Solo 4th Gen (USB), ALSA card `Gen`, device `hw:Gen`, format S32
- Displays: Waveshare 4" round HDMI 720×720 + 3.5" DSI touchscreen 800×480
- Monitors: KRK Rokit 5 (via Scarlett line outs, TRS balanced)
- Admin user uid=1000; raspotify runs as root
- Pi IP: `192.168.0.110` (DHCP reserved via MAC `dc:a6:32:b3:44:55`)
- SDL env vars: `SDL_VIDEODRIVER=wayland`, `WAYLAND_DISPLAY=wayland-0`, `XDG_RUNTIME_DIR=/run/user/1000`

## Systemd services

| Service | Runs as | Purpose |
|---------|---------|---------|
| `raspotify` | root | Spotify Connect (librespot) |
| `record-display` | admin | Album art display (display.py) |
| `control` | admin | Flask web UI (control.py) |
| `knob` | admin | Volume rotary encoder (knob.py) |
| `nav-knob` | root | Navigation rotary encoder (nav-knob.py) |

## Power Wiring

```
12V 5A PSU → Master Switch → 5A Fuse
    ├── Buck Converter USB-C → Pi
    ├── Buck Converter terminals → Round display (5V power only)
    └── MOSFET (GPIO18) → Motor system
    
Pi USB → Round display (data only, power cut)
Pi USB → Scarlett Solo (full power + data)
```

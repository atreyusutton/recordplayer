# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A retrofitted vinyl turntable with a Raspberry Pi 4 acting as a Spotify Connect device. The original motor/platter still spin real vinyl; a Waveshare 4" round 720×720 HDMI display in the center shows album art rotating at 33⅓ RPM.

## Deployment

This is a Pi-only runtime project — there are no local build steps or test suites. All code runs on the Pi.

**From dev machine:**
```bash
./deploy-display.sh [recordplayer.local]   # default host
```

**Directly on Pi (as root):**
```bash
sudo ./deploy-display.sh --local
```

The deploy script installs Python deps, copies files to `/home/admin/apps/recordplayer/`, installs the systemd unit, patches `LIBRESPOT_ONEVENT` into `/etc/raspotify/conf`, and restarts both services.

**Check status on Pi:**
```bash
sudo systemctl status record-display
sudo journalctl -u record-display -f
cat /tmp/now_playing.json
```

**Audio troubleshooting on Pi:**
```bash
bash diagnose-audio.sh
```

## Architecture

```
Spotify app  →  raspotify (librespot)  →  DAC HAT  →  RCA speakers
                     │
                 onevent.sh
                     │
              /tmp/now_playing.json   (polled every 1s)
                     │
                display.py  →  pygame Wayland  →  HDMI round display
```

### IPC: `/tmp/now_playing.json`

`onevent.sh` is the librespot `--onevent` hook. It writes this file on playback events:

- `track_changed` — writes full JSON with `event`, `title`, `artist`, `cover_url`; also persists track info to `/tmp/now_playing_state.json` for pause/resume
- `playing` — resume event (no metadata); restores track from state file
- `paused` / `stopped` — writes minimal event JSON

`display.py` polls the file by mtime (not content diff) every second from the main pygame loop.

### `display.py` rendering pipeline

1. **Poll** — `PlayerState.poll()` checks mtime of `/tmp/now_playing.json`
2. **Async load** — new `cover_url` triggers background thread download via `PlayerState.load_cover_async()` using a `requests.Session`; results are cached by URL (up to 5 entries) to avoid re-downloading on pause/resume; one automatic retry on failure
3. **Cross-fade** — 0.5s alpha blend when cover changes (`fade_active` flag + `fade_old_surf`); if a second track arrives mid-fade, cuts straight to new art
4. **Rotation** — `rotate_and_crop()` rotates the surface each frame; pygame `transform.rotate()` expands the canvas, so the result is center-cropped back to 720×720; angle is **subtracted** each frame (clockwise, matching a real record — pygame rotates CCW for positive angles)
5. **Render** — 60 FPS game loop; shows "Waiting for Spotify..." when no track loaded

Rotation speed: `RPM=33.333` → `200°/sec` → `~3.33°/frame` at 60 FPS. The display is physically circular so black rotation corners are hidden by the bezel — no diagonal pre-scaling needed.

## Key constants (display.py)

| Constant | Value | Purpose |
|----------|-------|---------|
| `DISPLAY_SIZE` | 720 | px, square surface; bezel makes it appear round |
| `FPS` | 60 | target frame rate |
| `DEG_PER_FRAME` | ~3.33° | 33⅓ RPM at 60 FPS |
| `FADE_DURATION` | 0.5s | cross-fade duration on track change |
| `POLL_INTERVAL` | 1.0s | how often to stat now_playing.json |
| `NOW_PLAYING_PATH` | `/tmp/now_playing.json` | IPC file |

## Pi environment

- OS: Raspberry Pi OS Bookworm, Wayland (labwc compositor)
- Python: 3.13.5, pygame 2.6.1, Pillow 11.1.0, requests
- Audio: InnoMaker PCM5122 DAC HAT, `hifiberry-dacplus` overlay, device `hw:sndrpihifiberry`
- Display: Waveshare 4" round HDMI LCD at `/dev/fb0` (vc4drmfb)
- Admin user uid=1000; raspotify/librespot runs as root
- Wayland socket: `/run/user/1000/wayland-0`
- SDL env vars required: `SDL_VIDEODRIVER=wayland`, `WAYLAND_DISPLAY=wayland-0`, `XDG_RUNTIME_DIR=/run/user/1000`

## Systemd unit notes

`record-display.service` runs as `admin` (uid=1000), depends on `labwc.service` and `network-online.target`, has a 3-second `ExecStartPre` sleep, and uses `WorkingDirectory=/tmp` (required for lgpio socket). It restarts automatically on crash (`Restart=always`).

## Planned features (NOTES.md)

- Physical rotary encoder for hardware volume control (GPIO)
- Second HDMI output with a control UI (React/PWA in Chromium kiosk, Spotify Web API OAuth)

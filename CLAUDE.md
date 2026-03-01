# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A retrofitted vinyl turntable with a Raspberry Pi 4 acting as a Spotify Connect device. The original motor/platter still spin real vinyl; a Waveshare 4" round 720×720 HDMI display in the center shows album art rotating at 33⅓ RPM. A second Flask web app (`control.py`) serves a touch-friendly Spotify control UI at port 8080.

## Deployment

This is a Pi-only runtime project — no local build steps or test suites. All code runs on the Pi.

**Standard deploy (from dev machine — git push auto-deploys):**
```bash
git push   # Pi's post-receive hook deploys to /home/admin/apps/recordplayer/
```

**After pushing, restart services if needed:**
```bash
ssh rasp-bumpy "sudo systemctl restart record-display control"
```

**IMPORTANT — onevent.sh sync:** Raspotify is configured to call `/usr/local/bin/onevent-recordplayer.sh`, not the repo's copy directly. After any change to `onevent.sh`, also run:
```bash
ssh rasp-bumpy "sudo cp /home/admin/apps/recordplayer/onevent.sh /usr/local/bin/onevent-recordplayer.sh && sudo systemctl restart raspotify"
```

**Check status on Pi:**
```bash
ssh rasp-bumpy "sudo systemctl status record-display control"
ssh rasp-bumpy "sudo journalctl -u record-display -f"
ssh rasp-bumpy "sudo journalctl -u control -f"
ssh rasp-bumpy "cat /tmp/now_playing.json"
```

**Audio troubleshooting:**
```bash
ssh rasp-bumpy "bash /home/admin/apps/recordplayer/diagnose-audio.sh"
```

**Debug album art issues:**
```bash
ssh rasp-bumpy "cat /tmp/onevent_debug.log"   # logs every librespot event
ssh rasp-bumpy "cat /tmp/now_playing_state.json"
```

## Architecture

```
Spotify app  ──Spotify Connect──▶  raspotify (librespot)  ──▶  DAC HAT  ──▶  RCA speakers
                                          │
                              /usr/local/bin/onevent-recordplayer.sh
                              (symlinked to repo's onevent.sh)
                                          │
                                 /tmp/now_playing.json        /tmp/now_playing_state.json
                                          │
                               display.py (polls 1s)
                                          │
                               pygame Wayland ──▶ round HDMI display

Browser / future kiosk  ──http://rasp-bumpy:8080──▶  control.py (Flask, port 8080)
                                                             │
                                                    Spotify Web API (OAuth)
```

## Key files

| File | Pi path | Purpose |
|------|---------|---------|
| `display.py` | `/home/admin/apps/recordplayer/display.py` | Spinning album art display |
| `onevent.sh` | `/home/admin/apps/recordplayer/onevent.sh` + `/usr/local/bin/onevent-recordplayer.sh` | librespot event hook |
| `control.py` | `/home/admin/apps/recordplayer/control.py` | Flask Spotify control backend |
| `static/index.html` | `/home/admin/apps/recordplayer/static/index.html` | Control UI frontend |
| `config.json` | `/home/admin/apps/recordplayer/config.json` | Spotify credentials — **gitignored, Pi only** |
| `tokens.json` | `/home/admin/apps/recordplayer/tokens.json` | OAuth tokens — **gitignored, Pi only** |
| `record-display.service` | `/etc/systemd/system/record-display.service` | Display systemd unit |
| `control.service` | `/etc/systemd/system/control.service` | Control UI systemd unit |
| `deploy-display.sh` | — | Deploy script |
| `setup.sh` | — | Raspotify + DAC setup |
| `diagnose-audio.sh` | — | Audio troubleshooting |

## IPC: `/tmp/now_playing.json`

`onevent.sh` is the librespot `--onevent` hook. Written via `python3 json.dumps()` (not bash printf) to correctly handle multi-artist tracks where librespot uses newlines as artist separators in the `ARTISTS` env var.

Events handled:
- `track_changed` — writes full JSON (`event`, `title`, `artist`, `cover_url`) + persists to `now_playing_state.json`
- `playing` — resume; restores from state file
- `paused` / `stopped` — writes minimal event JSON

`flock` serializes concurrent `track_changed` + `playing` invocations to prevent a race where `playing` reads stale state before `track_changed` has written it.

`display.py` polls by mtime every second. `poll()` only reacts to `event == "playing"` so paused/stopped events never accidentally clear or re-trigger artwork.

## display.py rendering pipeline

1. **Poll** — `PlayerState.poll()` checks mtime; only reacts to `"playing"` events with a changed `cover_url`
2. **Async load** — background thread download via `requests.Session`; URL-keyed cache (5 entries); one retry on failure
3. **Cross-fade** — 0.5s alpha blend on track change; cuts to new art if second track arrives mid-fade
4. **Rotation** — always spins at 33⅓ RPM regardless of play/pause state; **clockwise** (angle subtracted — pygame rotates CCW for positive values)
5. **Render** — 60 FPS; shows "Waiting for Spotify..." when no cover loaded

## control.py (Spotify Control UI)

Flask backend on port 8080. Credentials in `config.json` (gitignored). Tokens auto-refresh.

**Endpoints:**
- `GET /` — serves `static/index.html`
- `GET /login` → `GET /callback` — OAuth Authorization Code flow
- `GET /api/now-playing` — current playback state
- `POST /api/play|pause|next|previous|seek|volume` — playback commands
- `GET /api/playlists` — user playlists
- `POST /api/play-playlist` — play a playlist on the Pi device

Device targeting: caches the "Record Player" librespot device ID for 60s to avoid an extra API call on every command.

**First-time auth (once only):**
```bash
# On Mac — open SSH tunnel:
ssh -L 8080:localhost:8080 rasp-bumpy
# Then open browser to http://localhost:8080 and click Connect Spotify
# After login, close tunnel. Use http://rasp-bumpy:8080 forever after.
```

**Future kiosk mode (when second display arrives):**
```bash
chromium-browser --kiosk --noerrdialogs http://localhost:8080
```
Target display size: **500×282px** (3.5" 16:9). Test in browser with DevTools responsive mode (Cmd+Shift+M → 500×282).

## Pi environment

- OS: Raspberry Pi OS Bookworm, Wayland (labwc compositor)
- Python: 3.13.5, pygame 2.6.1, Pillow 11.1.0, requests, flask — installed
- Audio: InnoMaker PCM5122 DAC HAT, `hifiberry-dacplus` overlay, device `plughw:sndrpihifiberry`
- Display: Waveshare 4" round HDMI LCD, 720×720
- Admin user uid=1000; raspotify runs as root
- SDL env vars: `SDL_VIDEODRIVER=wayland`, `WAYLAND_DISPLAY=wayland-0`, `XDG_RUNTIME_DIR=/run/user/1000`

## Systemd services

| Service | Runs as | Depends on | Notes |
|---------|---------|------------|-------|
| `record-display` | admin | `labwc.service`, `network-online.target` | 3s ExecStartPre sleep; `WorkingDirectory=/tmp` |
| `control` | admin | `network-online.target` | Flask on 0.0.0.0:8080 |

## Upcoming features

- **Physical volume knob** — rotary encoder on GPIO, writes directly to ALSA mixer (no Spotify API needed)
- **Second display** — 3.5" 16:9 rectangular touchscreen on Pi's second HDMI output, runs control UI in Chromium kiosk

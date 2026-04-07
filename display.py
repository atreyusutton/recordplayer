#!/usr/bin/env python3
"""
Record Player Album Art Display
Runs on Raspberry Pi 4 with Waveshare 4" 720x720 round HDMI LCD.
Displays spinning album artwork while Spotify plays.
IPC: polls /tmp/now_playing.json written by onevent.sh
Sleep/wake: coordinated via /tmp/recordplayer_sleep and /tmp/recordplayer_wake
"""

import os
import subprocess
import sys
import json
import time
import io
import threading
from pathlib import Path

import requests
import pygame
from PIL import Image

# ── Constants ──────────────────────────────────────────────────────────────────
DISPLAY_SIZE = 720
RPM = 33.333
DEG_PER_SEC = RPM * 360 / 60   # 200 deg/sec
FPS = 60
DEG_PER_FRAME = DEG_PER_SEC / FPS  # ~3.33°

NOW_PLAYING_PATH = Path("/tmp/now_playing.json")
SLEEP_FILE = Path("/tmp/recordplayer_sleep")
WAKE_FILE = Path("/tmp/recordplayer_wake")
CONTROL_API = "http://localhost:8080/api/now-playing"
FADE_DURATION = 0.5   # seconds
POLL_INTERVAL = 1.0   # seconds
API_POLL_INTERVAL = 3.0  # seconds — poll Spotify API for non-local playback
COVER_TIMEOUT = 8     # seconds for HTTP requests
COVER_CACHE_SIZE = 5  # number of cover surfaces to keep in memory
SLEEP_AFTER = 2 * 60  # seconds of no play before sleeping


# ── Cover loading ──────────────────────────────────────────────────────────────

_http = requests.Session()
_cover_cache: dict[str, pygame.Surface] = {}
_cover_cache_order: list[str] = []


def pil_to_pygame(pil_image: Image.Image) -> pygame.Surface:
    data = pil_image.tobytes()
    return pygame.image.fromstring(data, pil_image.size, "RGBA")


def load_cover(url: str) -> pygame.Surface:
    """Download and scale cover art. Results are cached by URL."""
    if url in _cover_cache:
        return _cover_cache[url]

    resp = _http.get(url, timeout=COVER_TIMEOUT)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content)).convert("RGBA")
    img = img.resize((DISPLAY_SIZE, DISPLAY_SIZE), Image.LANCZOS)
    surf = pil_to_pygame(img)

    _cover_cache[url] = surf
    _cover_cache_order.append(url)
    if len(_cover_cache_order) > COVER_CACHE_SIZE:
        _cover_cache.pop(_cover_cache_order.pop(0), None)

    return surf


# ── Helpers ────────────────────────────────────────────────────────────────────

def rotate_and_crop(source: pygame.Surface, angle: float) -> pygame.Surface:
    """Rotate source by angle degrees, center-crop result to DISPLAY_SIZE×DISPLAY_SIZE."""
    rotated = pygame.transform.rotate(source, angle)
    rw, rh = rotated.get_size()
    x = (rw - DISPLAY_SIZE) // 2
    y = (rh - DISPLAY_SIZE) // 2
    cropped = pygame.Surface((DISPLAY_SIZE, DISPLAY_SIZE))
    cropped.blit(rotated, (0, 0), pygame.Rect(x, y, DISPLAY_SIZE, DISPLAY_SIZE))
    return cropped


def _screen_power(on: bool):
    subprocess.run(["vcgencmd", "display_power", "1" if on else "0"], check=False)


def _enter_sleep():
    """Write sleep file and blank screens."""
    SLEEP_FILE.write_text(str(time.time()))
    WAKE_FILE.unlink(missing_ok=True)
    _screen_power(False)


def _exit_sleep():
    """Remove sleep file and turn screens on."""
    SLEEP_FILE.unlink(missing_ok=True)
    WAKE_FILE.unlink(missing_ok=True)
    _screen_power(True)


def _check_wake() -> bool:
    """Return True if a wake trigger is pending."""
    if WAKE_FILE.exists():
        return True
    # Also wake if a new playing event arrived
    try:
        data = json.loads(NOW_PLAYING_PATH.read_text())
        if data.get("event") == "playing":
            return True
    except Exception:
        pass
    return False


# ── State ──────────────────────────────────────────────────────────────────────

class PlayerState:
    def __init__(self):
        self.cover_url: str = ""
        self._mtime: float = 0.0
        self._lock = threading.Lock()
        self.cover_surface: pygame.Surface | None = None
        self._last_play_time: float = 0.0  # 0 = never played yet

    def poll(self) -> bool:
        """Check /tmp/now_playing.json for changes. Returns True if cover should update.

        Only reacts to 'playing' events so that paused/stopped events (which carry
        no cover_url) never accidentally clear or re-trigger a cover load.
        """
        try:
            mtime = NOW_PLAYING_PATH.stat().st_mtime
        except FileNotFoundError:
            return False
        if mtime == self._mtime:
            return False
        self._mtime = mtime
        try:
            data = json.loads(NOW_PLAYING_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        with self._lock:
            event = data.get("event")
            if event == "playing":
                self._last_play_time = time.monotonic()
            if event != "playing":
                return False
            new_url = data.get("cover_url", "")
            if new_url != self.cover_url:
                self.cover_url = new_url
                return True
        return False

    @property
    def idle_seconds(self) -> float:
        if self._last_play_time == 0.0:
            return 0.0  # never played — don't trigger sleep on boot
        return time.monotonic() - self._last_play_time

    @property
    def has_ever_played(self) -> bool:
        return self._last_play_time > 0.0

    def poll_api(self) -> bool:
        """Poll control.py Spotify API for cover art from any device.
        Returns True if cover should update."""
        try:
            resp = _http.get(CONTROL_API, timeout=3)
            if not resp.ok:
                return False
            data = resp.json()
        except Exception:
            return False
        with self._lock:
            track = data.get("track")
            if not track:
                return False
            # Any playback (any device) keeps the display alive
            if data.get("playing"):
                self._last_play_time = time.monotonic()
            art_url = track.get("art", "")
            if art_url and art_url != self.cover_url:
                self.cover_url = art_url
                return True
        return False

    def load_cover_async(self, url: str, callback):
        """Download cover art in a background thread; retry once on failure."""
        def _worker():
            for attempt in range(2):
                try:
                    callback(load_cover(url))
                    return
                except Exception as e:
                    label = "retrying" if attempt == 0 else "giving up"
                    print(f"[display] cover load failed ({label}): {e}", file=sys.stderr)
        threading.Thread(target=_worker, daemon=True).start()


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    # Wayland env (also set in systemd unit, but belt-and-suspenders)
    os.environ.setdefault("SDL_VIDEODRIVER", "wayland")
    os.environ.setdefault("WAYLAND_DISPLAY", "wayland-0")
    os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")

    # Clean up stale sleep/wake files from previous run
    SLEEP_FILE.unlink(missing_ok=True)
    WAKE_FILE.unlink(missing_ok=True)

    pygame.display.init()
    pygame.font.init()
    pygame.mouse.set_visible(False)
    pygame.display.set_caption("Record Player")
    screen = pygame.display.set_mode((DISPLAY_SIZE, DISPLAY_SIZE), pygame.FULLSCREEN | pygame.NOFRAME)
    clock = pygame.time.Clock()

    state = PlayerState()
    sleeping = False

    angle = 0.0

    # Cross-fade state
    fade_active = False
    fade_start = 0.0
    fade_old_surf: pygame.Surface | None = None
    new_cover_pending: pygame.Surface | None = None

    last_poll = 0.0
    last_api_poll = 0.0

    def on_cover_loaded(surf: pygame.Surface):
        nonlocal new_cover_pending
        new_cover_pending = surf

    def _trigger_cover_load():
        nonlocal new_cover_pending, fade_active
        if state.cover_url:
            state.load_cover_async(state.cover_url, on_cover_loaded)
        else:
            new_cover_pending = None
            state.cover_surface = None
            fade_active = False

    while True:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit(0)

        now = time.monotonic()

        # ── Poll IPC (librespot local events) ──
        if now - last_poll >= POLL_INTERVAL:
            last_poll = now

            if sleeping:
                if _check_wake():
                    sleeping = False
                    _exit_sleep()
                    print("[display] waking up", file=sys.stderr)
                    state.poll()
                else:
                    continue
            else:
                if state.has_ever_played and state.idle_seconds > SLEEP_AFTER:
                    sleeping = True
                    _enter_sleep()
                    print("[display] entering sleep", file=sys.stderr)
                    continue

                if state.poll():
                    _trigger_cover_load()

        # ── Poll Spotify API (catches playback on other devices) ──
        if not sleeping and now - last_api_poll >= API_POLL_INTERVAL:
            last_api_poll = now
            if state.poll_api():
                _trigger_cover_load()

        if sleeping:
            continue

        # ── Swap in newly downloaded cover ──
        if new_cover_pending is not None:
            if fade_active:
                state.cover_surface = new_cover_pending
                new_cover_pending = None
                fade_active = False
            else:
                fade_old_surf = rotate_and_crop(state.cover_surface, angle) if state.cover_surface else None
                state.cover_surface = new_cover_pending
                new_cover_pending = None
                fade_active = True
                fade_start = time.monotonic()

        # ── Rotation (negative = clockwise, matching a real record) ──
        angle = (angle - DEG_PER_FRAME) % 360

        # ── Render ──
        screen.fill((0, 0, 0))

        if state.cover_surface is not None:
            current_frame = rotate_and_crop(state.cover_surface, angle)

            if fade_active:
                elapsed = time.monotonic() - fade_start
                alpha = min(elapsed / FADE_DURATION, 1.0)
                if alpha >= 1.0:
                    fade_active = False
                    fade_old_surf = None

                if fade_old_surf is not None and alpha < 1.0:
                    screen.blit(fade_old_surf, (0, 0))
                    new_alpha_surf = current_frame.copy().convert_alpha()
                    new_alpha_surf.set_alpha(int(alpha * 255))
                    screen.blit(new_alpha_surf, (0, 0))
                else:
                    screen.blit(current_frame, (0, 0))
            else:
                screen.blit(current_frame, (0, 0))

        # No "waiting" text — just black until first track plays

        pygame.display.flip()


if __name__ == "__main__":
    main()

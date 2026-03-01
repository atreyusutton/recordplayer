#!/usr/bin/env python3
"""
Record Player Album Art Display
Runs on Raspberry Pi 4 with Waveshare 4" 720x720 round HDMI LCD.
Displays spinning album artwork while Spotify plays.
IPC: polls /tmp/now_playing.json written by onevent.sh
"""

import os
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
FADE_DURATION = 0.5   # seconds
POLL_INTERVAL = 1.0   # seconds
COVER_TIMEOUT = 8     # seconds for HTTP requests
COVER_CACHE_SIZE = 5  # number of cover surfaces to keep in memory


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

def make_waiting_surface() -> pygame.Surface:
    surf = pygame.Surface((DISPLAY_SIZE, DISPLAY_SIZE))
    surf.fill((0, 0, 0))
    font = pygame.font.SysFont("dejavusans", 28)
    text = font.render("Waiting for Spotify...", True, (180, 180, 180))
    surf.blit(text, text.get_rect(center=(DISPLAY_SIZE // 2, DISPLAY_SIZE // 2)))
    return surf


def rotate_and_crop(source: pygame.Surface, angle: float) -> pygame.Surface:
    """Rotate source by angle degrees, center-crop result to DISPLAY_SIZE×DISPLAY_SIZE."""
    rotated = pygame.transform.rotate(source, angle)
    rw, rh = rotated.get_size()
    x = (rw - DISPLAY_SIZE) // 2
    y = (rh - DISPLAY_SIZE) // 2
    cropped = pygame.Surface((DISPLAY_SIZE, DISPLAY_SIZE))
    cropped.blit(rotated, (0, 0), pygame.Rect(x, y, DISPLAY_SIZE, DISPLAY_SIZE))
    return cropped


# ── State ──────────────────────────────────────────────────────────────────────

class PlayerState:
    def __init__(self):
        self.cover_url: str = ""
        self._mtime: float = 0.0
        self._lock = threading.Lock()
        self.cover_surface: pygame.Surface | None = None

    def poll(self) -> bool:
        """Check /tmp/now_playing.json for changes. Returns True if cover URL changed."""
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
            new_url = data.get("cover_url", "")
            if new_url and new_url != self.cover_url:
                self.cover_url = new_url
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

    pygame.init()
    pygame.mouse.set_visible(False)
    pygame.display.set_caption("Record Player")
    screen = pygame.display.set_mode((DISPLAY_SIZE, DISPLAY_SIZE), pygame.FULLSCREEN | pygame.NOFRAME)
    clock = pygame.time.Clock()

    state = PlayerState()

    angle = 0.0

    # Cross-fade state
    fade_active = False
    fade_start = 0.0
    fade_old_surf: pygame.Surface | None = None
    new_cover_pending: pygame.Surface | None = None

    waiting_surf = make_waiting_surface()
    has_track = False
    last_poll = 0.0

    def on_cover_loaded(surf: pygame.Surface):
        nonlocal new_cover_pending
        new_cover_pending = surf

    while True:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                pygame.quit()
                sys.exit(0)

        # ── Poll IPC ──
        now = time.monotonic()
        if now - last_poll >= POLL_INTERVAL:
            last_poll = now
            if state.poll():
                if state.cover_url:
                    state.load_cover_async(state.cover_url, on_cover_loaded)
                has_track = bool(state.cover_url or state.cover_surface)

        # ── Swap in newly downloaded cover ──
        if new_cover_pending is not None:
            if fade_active:
                # A second track arrived mid-fade; cut straight to new art
                state.cover_surface = new_cover_pending
                new_cover_pending = None
                fade_active = False
            else:
                fade_old_surf = rotate_and_crop(state.cover_surface, angle) if state.cover_surface else None
                state.cover_surface = new_cover_pending
                new_cover_pending = None
                fade_active = True
                fade_start = time.monotonic()
            has_track = True

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

        elif not has_track:
            screen.blit(waiting_surf, (0, 0))

        pygame.display.flip()


if __name__ == "__main__":
    main()

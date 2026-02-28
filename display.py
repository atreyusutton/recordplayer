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
import urllib.request
from pathlib import Path

import pygame
from PIL import Image

try:
    import lgpio
    MOTOR_PIN = 17  # BCM GPIO17, physical pin 11 (GPIO18 is I2S PCM_CLK for HiFiBerry DAC)
    _gpio_handle = lgpio.gpiochip_open(0)
    lgpio.gpio_claim_output(_gpio_handle, MOTOR_PIN, 0)  # 0 = start LOW (motor off)
    MOTOR_AVAILABLE = True
    print("[motor] GPIO ready, motor OFF", flush=True)
except Exception as e:
    MOTOR_AVAILABLE = False
    print(f"[motor] GPIO unavailable: {e}", flush=True)

def set_motor(on: bool):
    if MOTOR_AVAILABLE:
        lgpio.gpio_write(_gpio_handle, MOTOR_PIN, 1 if on else 0)

# ── Constants ──────────────────────────────────────────────────────────────────
DISPLAY_SIZE = 720
# The display is physically round, so black corners produced by rotation are
# hidden by the circular bezel — no need to pre-scale to the diagonal.

RPM = 33.333
DEG_PER_SEC = RPM * 360 / 60   # 200 deg/sec
FPS = 60
DEG_PER_FRAME = DEG_PER_SEC / FPS  # ~3.33°

NOW_PLAYING_PATH = Path("/tmp/now_playing.json")
FADE_DURATION = 0.5  # seconds


# ── Helpers ────────────────────────────────────────────────────────────────────

def pil_to_pygame(pil_image: Image.Image) -> pygame.Surface:
    """Convert PIL Image (RGBA) to a pygame Surface."""
    data = pil_image.tobytes()
    return pygame.image.fromstring(data, pil_image.size, "RGBA")


def load_cover(url: str) -> pygame.Surface:
    """Download cover art URL, scale to 720×720, return pygame Surface."""
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = resp.read()
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    img = img.resize((DISPLAY_SIZE, DISPLAY_SIZE), Image.LANCZOS)
    return pil_to_pygame(img)


def make_waiting_surface() -> pygame.Surface:
    """Black surface with centered 'Waiting for Spotify...' text."""
    surf = pygame.Surface((DISPLAY_SIZE, DISPLAY_SIZE))
    surf.fill((0, 0, 0))
    font = pygame.font.SysFont("dejavusans", 28)
    text = font.render("Waiting for Spotify...", True, (180, 180, 180))
    rect = text.get_rect(center=(DISPLAY_SIZE // 2, DISPLAY_SIZE // 2))
    surf.blit(text, rect)
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
        self.event: str = "stopped"
        self.cover_url: str = ""
        self._mtime: float = 0.0
        self._lock = threading.Lock()
        self.cover_surface: pygame.Surface | None = None
        self.pending_cover: pygame.Surface | None = None

    def poll(self) -> bool:
        """Check /tmp/now_playing.json for changes. Returns True if changed."""
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
            self.event = data.get("event", "stopped")
            new_url = data.get("cover_url", "")
            if new_url and new_url != self.cover_url:
                self.cover_url = new_url
                return True  # new artwork needed
        return True  # event change

    def load_cover_async(self, url: str, callback):
        """Download cover art in a background thread, call callback(surface) when done."""
        def _worker():
            try:
                surf = load_cover(url)
                callback(surf)
            except Exception as e:
                print(f"[display] cover download failed: {e}", file=sys.stderr)
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
    spinning = False

    # Cross-fade state
    fade_active = False
    fade_start = 0.0
    fade_old_surf: pygame.Surface | None = None
    new_cover_pending: pygame.Surface | None = None

    waiting_surf = make_waiting_surface()
    has_track = False

    last_poll = 0.0
    POLL_INTERVAL = 1.0

    def on_cover_loaded(surf: pygame.Surface):
        nonlocal new_cover_pending
        new_cover_pending = surf

    while True:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                set_motor(False)
                pygame.quit()
                sys.exit(0)
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                set_motor(False)
                pygame.quit()
                sys.exit(0)

        # ── Poll IPC ──
        now = time.monotonic()
        if now - last_poll >= POLL_INTERVAL:
            last_poll = now
            changed = state.poll()
            if changed:
                now_playing = (state.event == "playing")
                if now_playing != spinning:
                    set_motor(now_playing)
                spinning = now_playing
                if state.cover_url and changed:
                    state.load_cover_async(state.cover_url, on_cover_loaded)
                has_track = bool(state.cover_url or state.cover_surface)

        # ── Check for newly loaded cover ──
        if new_cover_pending is not None:
            if fade_active:
                state.cover_surface = new_cover_pending
                new_cover_pending = None
                fade_active = False
            else:
                if state.cover_surface is not None:
                    fade_old_surf = rotate_and_crop(state.cover_surface, angle)
                else:
                    fade_old_surf = None
                state.cover_surface = new_cover_pending
                new_cover_pending = None
                fade_active = True
                fade_start = time.monotonic()
            has_track = True

        # ── Rotation ──
        if spinning:
            angle = (angle + DEG_PER_FRAME) % 360

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
    try:
        main()
    finally:
        set_motor(False)
        if MOTOR_AVAILABLE:
            lgpio.gpiochip_close(_gpio_handle)

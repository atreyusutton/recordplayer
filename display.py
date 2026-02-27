#!/usr/bin/env python3
"""
Record Player Album Art Display
Runs on Raspberry Pi 4 with Waveshare 4" 720x720 round HDMI LCD.
Displays spinning album artwork + track info while Spotify plays.
IPC: polls /tmp/now_playing.json written by onevent.sh
"""

import os
import sys
import json
import time
import math
import io
import threading
import urllib.request
from pathlib import Path

import pygame
from PIL import Image, ImageDraw, ImageFont

# ── Constants ──────────────────────────────────────────────────────────────────
DISPLAY_SIZE = 720
ARTWORK_SIZE = 720
# Pre-scale to diagonal to avoid black corners during rotation: 720 * sqrt(2) ≈ 1018
ROTATE_SIZE = math.ceil(DISPLAY_SIZE * math.sqrt(2))
# Round up to nearest even for clean blitting
if ROTATE_SIZE % 2 != 0:
    ROTATE_SIZE += 1

RPM = 33.333
DEG_PER_SEC = RPM * 360 / 60   # 200 deg/sec
FPS = 60
DEG_PER_FRAME = DEG_PER_SEC / FPS  # ~3.33°

NOW_PLAYING_PATH = Path("/tmp/now_playing.json")
FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FADE_DURATION = 0.5  # seconds

# Text overlay: bottom 22% of the circle
OVERLAY_H = int(DISPLAY_SIZE * 0.22)
OVERLAY_Y = DISPLAY_SIZE - OVERLAY_H

# Font sizes
TITLE_FONT_SIZE = 32
ARTIST_FONT_SIZE = 22


# ── Helpers ────────────────────────────────────────────────────────────────────

def pil_to_pygame(pil_image: Image.Image) -> pygame.Surface:
    """Convert PIL Image (RGBA) to a pygame Surface."""
    data = pil_image.tobytes()
    return pygame.image.fromstring(data, pil_image.size, "RGBA")


def load_cover(url: str) -> pygame.Surface:
    """Download cover art URL, scale/crop to ROTATE_SIZE×ROTATE_SIZE, return pygame Surface."""
    with urllib.request.urlopen(url, timeout=10) as resp:
        raw = resp.read()
    img = Image.open(io.BytesIO(raw)).convert("RGBA")
    # Scale to fill ROTATE_SIZE keeping aspect ratio, then center-crop
    img = img.resize((ROTATE_SIZE, ROTATE_SIZE), Image.LANCZOS)
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


def render_text_overlay(title: str, artist: str) -> pygame.Surface:
    """
    Render a semi-transparent pill at the bottom of the circle with title/artist.
    Returns a 720×720 RGBA surface (most pixels transparent).
    """
    overlay = Image.new("RGBA", (DISPLAY_SIZE, DISPLAY_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Semi-transparent black bar
    bar_rect = [0, OVERLAY_Y, DISPLAY_SIZE, DISPLAY_SIZE]
    draw.rectangle(bar_rect, fill=(0, 0, 0, 180))

    try:
        font_title = ImageFont.truetype(FONT_PATH, TITLE_FONT_SIZE)
        font_artist = ImageFont.truetype(FONT_PATH, ARTIST_FONT_SIZE)
    except (OSError, IOError):
        font_title = ImageFont.load_default()
        font_artist = font_title

    # Title: white, centered
    title_y = OVERLAY_Y + 12
    bbox = draw.textbbox((0, 0), title, font=font_title)
    title_w = bbox[2] - bbox[0]
    title_x = (DISPLAY_SIZE - title_w) // 2
    # Truncate if too wide
    while title_w > DISPLAY_SIZE - 20 and len(title) > 5:
        title = title[:-1]
        bbox = draw.textbbox((0, 0), title + "…", font=font_title)
        title_w = bbox[2] - bbox[0]
    if title_w > DISPLAY_SIZE - 20:
        title = title + "…"
        bbox = draw.textbbox((0, 0), title, font=font_title)
        title_w = bbox[2] - bbox[0]
    title_x = (DISPLAY_SIZE - title_w) // 2
    draw.text((title_x, title_y), title, font=font_title, fill=(255, 255, 255, 255))

    # Artist: grey, centered below title
    artist_y = title_y + TITLE_FONT_SIZE + 6
    bbox = draw.textbbox((0, 0), artist, font=font_artist)
    artist_w = bbox[2] - bbox[0]
    while artist_w > DISPLAY_SIZE - 20 and len(artist) > 5:
        artist = artist[:-1]
        bbox = draw.textbbox((0, 0), artist + "…", font=font_artist)
        artist_w = bbox[2] - bbox[0]
    artist_x = (DISPLAY_SIZE - artist_w) // 2
    draw.text((artist_x, artist_y), artist, font=font_artist, fill=(180, 180, 180, 255))

    return pil_to_pygame(overlay)


def rotate_and_crop(source: pygame.Surface, angle: float) -> pygame.Surface:
    """
    Rotate source (ROTATE_SIZE×ROTATE_SIZE) by angle degrees,
    then center-crop to DISPLAY_SIZE×DISPLAY_SIZE.
    """
    rotated = pygame.transform.rotate(source, angle)
    # rotated may be slightly larger; center-crop
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
        self.title: str = ""
        self.artist: str = ""
        self.cover_url: str = ""
        self._mtime: float = 0.0
        self._lock = threading.Lock()
        # Loaded artwork (ROTATE_SIZE×ROTATE_SIZE pygame Surface)
        self.cover_surface: pygame.Surface | None = None
        self.pending_cover: pygame.Surface | None = None
        self.pending_meta: dict | None = None

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
            self.title = data.get("title", "")
            self.artist = data.get("artist", "")
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
        t = threading.Thread(target=_worker, daemon=True)
        t.start()


# ── Main loop ─────────────────────────────────────────────────────────────────

def main():
    # Wayland env (also set in systemd unit, but belt-and-suspenders)
    os.environ.setdefault("SDL_VIDEODRIVER", "wayland")
    os.environ.setdefault("WAYLAND_DISPLAY", "wayland-0")
    os.environ.setdefault("XDG_RUNTIME_DIR", "/run/user/1000")

    pygame.init()
    pygame.display.set_caption("Record Player")
    screen = pygame.display.set_mode((DISPLAY_SIZE, DISPLAY_SIZE), pygame.NOFRAME)
    clock = pygame.time.Clock()

    state = PlayerState()

    # Display state
    angle = 0.0
    spinning = False

    # Cross-fade state
    fade_active = False
    fade_start = 0.0
    fade_old_surf: pygame.Surface | None = None   # old artwork (already rotated+cropped)
    new_cover_pending: pygame.Surface | None = None  # waiting to start fade

    # Overlay
    overlay_surf: pygame.Surface | None = None

    # Waiting screen
    waiting_surf = make_waiting_surface()
    has_track = False

    # For alpha blending we need a surface with per-pixel alpha
    def make_alpha_copy(surf: pygame.Surface) -> pygame.Surface:
        s = surf.convert_alpha()
        return s

    last_poll = 0.0
    POLL_INTERVAL = 1.0

    def on_cover_loaded(surf: pygame.Surface):
        nonlocal new_cover_pending
        new_cover_pending = surf

    while True:
        dt = clock.tick(FPS) / 1000.0  # seconds since last frame

        # ── Events ──
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
            changed = state.poll()
            if changed:
                spinning = (state.event == "playing")
                if state.cover_url and changed:
                    # Only reload artwork if URL changed (checked inside poll)
                    state.load_cover_async(state.cover_url, on_cover_loaded)
                if state.title or state.artist:
                    overlay_surf = render_text_overlay(state.title, state.artist)
                has_track = bool(state.cover_url or state.cover_surface)

        # ── Check for newly loaded cover ──
        if new_cover_pending is not None:
            if fade_active:
                # Already fading — snap to new immediately
                state.cover_surface = new_cover_pending
                new_cover_pending = None
                fade_active = False
            else:
                # Start cross-fade
                if state.cover_surface is not None:
                    # Capture current rotated frame as fade_old
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
                    # Blit old frame fully opaque
                    screen.blit(fade_old_surf, (0, 0))
                    # Blit new frame with increasing alpha
                    new_alpha_surf = current_frame.copy().convert_alpha()
                    new_alpha_surf.set_alpha(int(alpha * 255))
                    screen.blit(new_alpha_surf, (0, 0))
                else:
                    screen.blit(current_frame, (0, 0))
            else:
                screen.blit(current_frame, (0, 0))

            # Text overlay (RGBA with transparency)
            if overlay_surf is not None:
                screen.blit(overlay_surf, (0, 0))

        elif not has_track:
            screen.blit(waiting_surf, (0, 0))

        pygame.display.flip()


if __name__ == "__main__":
    main()

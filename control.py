#!/usr/bin/env python3
"""
Spotify Control Backend
Runs on Raspberry Pi, serves a web UI for controlling Spotify playback.
Access at http://rasp-bumpy:8080 from any browser on the local network.

First-time setup: open an SSH tunnel then visit http://localhost:8080
  ssh -L 8080:localhost:8080 rasp-bumpy
"""

import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import requests
from flask import Flask, jsonify, redirect, request, send_file, session

# ── Config & paths ─────────────────────────────────────────────────────────────

BASE = Path(__file__).parent
CONFIG_PATH = BASE / "config.json"
TOKENS_PATH = BASE / "tokens.json"

if not CONFIG_PATH.exists():
    print(f"ERROR: {CONFIG_PATH} not found. Create it with client_id and client_secret.",
          file=sys.stderr)
    sys.exit(1)

_cfg = json.loads(CONFIG_PATH.read_text())
CLIENT_ID     = _cfg["client_id"]
CLIENT_SECRET = _cfg["client_secret"]

REDIRECT_URI = "http://127.0.0.1:8080/callback"
SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "playlist-read-private",
    "playlist-read-collaborative",
    "user-read-playback-queue",
])

SPOTIFY_AUTH  = "https://accounts.spotify.com/authorize"
SPOTIFY_TOKEN = "https://accounts.spotify.com/api/token"
SPOTIFY_API   = "https://api.spotify.com/v1"
DEVICE_NAME   = "Record Player"

app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

ALSA_CARD    = "sndrpihifiberry"
ALSA_CONTROL = "Digital"

# ── ALSA system volume ──────────────────────────────────────────────────────────

def _alsa_get() -> tuple[int, bool]:
    """Return (volume_percent 0-100, muted bool) from ALSA Digital control."""
    try:
        out = subprocess.check_output(
            ["amixer", "-c", ALSA_CARD, "sget", ALSA_CONTROL], text=True
        )
        m = re.search(r"\[(\d+)%\]", out)
        vol = int(m.group(1)) if m else 50
        muted = "[off]" in out
        return vol, muted
    except Exception:
        return 50, False

def _alsa_set(vol: int):
    subprocess.run(
        ["amixer", "-c", ALSA_CARD, "-q", "sset", ALSA_CONTROL, f"{vol}%"],
        check=False,
    )

# ── Token management ───────────────────────────────────────────────────────────

def _load_tokens() -> dict | None:
    if TOKENS_PATH.exists():
        return json.loads(TOKENS_PATH.read_text())
    return None

def _save_tokens(tokens: dict):
    TOKENS_PATH.write_text(json.dumps(tokens))
    TOKENS_PATH.chmod(0o600)

def _get_token() -> str | None:
    tokens = _load_tokens()
    if not tokens:
        return None
    # Refresh if expiring within 60 seconds
    if time.time() > tokens.get("expires_at", 0) - 60:
        resp = requests.post(SPOTIFY_TOKEN, data={
            "grant_type":    "refresh_token",
            "refresh_token": tokens["refresh_token"],
            "client_id":     CLIENT_ID,
            "client_secret": CLIENT_SECRET,
        }, timeout=10)
        if not resp.ok:
            print(f"[control] token refresh failed: {resp.status_code} {resp.text}", file=sys.stderr)
            return None
        data = resp.json()
        tokens["access_token"] = data["access_token"]
        tokens["expires_at"]   = time.time() + data["expires_in"]
        if "refresh_token" in data:
            tokens["refresh_token"] = data["refresh_token"]
        _save_tokens(tokens)
    return tokens["access_token"]

# ── Spotify API helpers ────────────────────────────────────────────────────────

def _headers() -> dict:
    return {"Authorization": f"Bearer {_get_token()}"}

def _get(path: str, **kwargs):
    return requests.get(f"{SPOTIFY_API}{path}", headers=_headers(), timeout=8, **kwargs)

def _post(path: str, **kwargs):
    return requests.post(f"{SPOTIFY_API}{path}", headers=_headers(), timeout=8, **kwargs)

def _put(path: str, **kwargs):
    return requests.put(f"{SPOTIFY_API}{path}", headers=_headers(), timeout=8, **kwargs)

# Cache the Pi device ID for 60s to avoid an extra API call on every command
_device_cache: tuple[str, float] = ("", 0.0)

def _pi_device_id() -> str | None:
    global _device_cache
    cached_id, cached_at = _device_cache
    if cached_id and time.time() - cached_at < 60:
        return cached_id
    resp = _get("/me/player/devices")
    if not resp.ok:
        return None
    for dev in resp.json().get("devices", []):
        if dev["name"] == DEVICE_NAME:
            _device_cache = (dev["id"], time.time())
            return dev["id"]
    return None

# ── OAuth routes ───────────────────────────────────────────────────────────────

@app.get("/login")
def login():
    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state
    params = {
        "client_id":     CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  REDIRECT_URI,
        "state":         state,
        "scope":         SCOPES,
    }
    return redirect(f"{SPOTIFY_AUTH}?{urllib.parse.urlencode(params)}")

@app.get("/callback")
def callback():
    error = request.args.get("error")
    code  = request.args.get("code")
    if error or not code:
        return f"Spotify auth error: {error}", 400

    resp = requests.post(SPOTIFY_TOKEN, data={
        "grant_type":   "authorization_code",
        "code":         code,
        "redirect_uri": REDIRECT_URI,
        "client_id":    CLIENT_ID,
        "client_secret": CLIENT_SECRET,
    }, timeout=10)

    if not resp.ok:
        return f"Token exchange failed: {resp.text}", 400

    data = resp.json()
    _save_tokens({
        "access_token":  data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at":    time.time() + data["expires_in"],
    })
    return redirect("/")

# ── Frontend ───────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return send_file(BASE / "static" / "index.html")

# ── Playback state ─────────────────────────────────────────────────────────────

@app.get("/api/now-playing")
def now_playing():
    if not _load_tokens():
        return jsonify({"error": "not_authenticated"}), 401

    resp = _get("/me/player")

    if resp.status_code == 204:          # Nothing playing
        return jsonify({"playing": False, "track": None})
    if resp.status_code == 401:
        return jsonify({"error": "not_authenticated"}), 401
    if not resp.ok:
        return jsonify({"error": "api_error"}), 502

    data  = resp.json()
    item  = data.get("item") or {}
    album = item.get("album") or {}
    images = album.get("images") or []

    next_track = None
    try:
        q_resp = _get("/me/player/queue")
        if q_resp.ok:
            q_items = q_resp.json().get("queue") or []
            if q_items:
                n = q_items[0]
                n_images = (n.get("album") or {}).get("images") or []
                next_track = {
                    "name":    n.get("name", ""),
                    "artists": ", ".join(a["name"] for a in n.get("artists", [])),
                    "art":     n_images[0]["url"] if n_images else "",
                }
    except Exception:
        pass

    return jsonify({
        "playing":    data.get("is_playing", False),
        "track": {
            "name":        item.get("name", ""),
            "artists":     ", ".join(a["name"] for a in item.get("artists", [])),
            "album":       album.get("name", ""),
            "art":         images[0]["url"] if images else "",
            "duration_ms": item.get("duration_ms", 0),
            "progress_ms": data.get("progress_ms", 0),
        } if item else None,
        "volume":     _alsa_get()[0],
        "device":     (data.get("device") or {}).get("name", ""),
        "next_track": next_track,
    })

# ── Playback commands ──────────────────────────────────────────────────────────

@app.post("/api/play")
def play():
    dev = _pi_device_id()
    _put("/me/player/play", params={"device_id": dev} if dev else {})
    return jsonify({"ok": True})

@app.post("/api/pause")
def pause():
    dev = _pi_device_id()
    _put("/me/player/pause", params={"device_id": dev} if dev else {})
    return jsonify({"ok": True})

@app.post("/api/next")
def next_track():
    dev = _pi_device_id()
    _post("/me/player/next", params={"device_id": dev} if dev else {})
    return jsonify({"ok": True})

@app.post("/api/previous")
def previous_track():
    dev = _pi_device_id()
    _post("/me/player/previous", params={"device_id": dev} if dev else {})
    return jsonify({"ok": True})

@app.post("/api/seek")
def seek():
    pos_ms = int(request.json.get("position_ms", 0))
    dev = _pi_device_id()
    params = {"position_ms": pos_ms}
    if dev:
        params["device_id"] = dev
    _put("/me/player/seek", params=params)
    return jsonify({"ok": True})

@app.post("/api/volume")
def volume():
    vol = max(0, min(100, int(request.json.get("volume", 50))))
    _alsa_set(vol)
    return jsonify({"ok": True})

# ── Playlists ──────────────────────────────────────────────────────────────────

@app.get("/api/playlists")
def playlists():
    resp = _get("/me/playlists", params={"limit": 50})
    if not resp.ok:
        return jsonify({"error": "api_error"}), 502
    items = [p for p in resp.json().get("items", []) if p]
    return jsonify([{
        "id":     p["id"],
        "name":   p["name"],
        "tracks": (p.get("tracks") or p.get("items") or {}).get("total", 0),
        "art":    (p.get("images") or [{}])[0].get("url", ""),
    } for p in items])

@app.post("/api/play-playlist")
def play_playlist():
    playlist_id = request.json.get("playlist_id")
    dev = _pi_device_id()
    params = {"device_id": dev} if dev else {}
    _put("/me/player/play",
         params=params,
         json={"context_uri": f"spotify:playlist:{playlist_id}"})
    return jsonify({"ok": True})

@app.get("/api/playlist/<playlist_id>/tracks")
def playlist_tracks(playlist_id):
    resp = _get(f"/playlists/{playlist_id}/items", params={
        "limit": 50,
        "fields": "items(item(id,name,duration_ms,artists,album(images),uri))",
    })
    if not resp.ok:
        return jsonify({"error": "api_error"}), 502
    tracks = []
    for item in resp.json().get("items", []):
        t = item.get("item")
        if not t:
            continue
        images = (t.get("album") or {}).get("images") or []
        tracks.append({
            "id":          t.get("id", ""),
            "name":        t.get("name", ""),
            "artists":     ", ".join(a["name"] for a in t.get("artists", [])),
            "duration_ms": t.get("duration_ms", 0),
            "art":         images[0]["url"] if images else "",
            "uri":         t.get("uri", ""),
        })
    return jsonify(tracks)

@app.post("/api/play-track")
def play_track():
    data = request.json
    track_uri    = data.get("track_uri")
    playlist_uri = data.get("playlist_uri")
    offset       = data.get("offset")
    dev = _pi_device_id()
    params = {"device_id": dev} if dev else {}
    body = {}
    if playlist_uri and offset is not None:
        body["context_uri"] = playlist_uri
        body["offset"]      = {"position": offset}
    else:
        body["uris"] = [track_uri]
    _put("/me/player/play", params=params, json=body)
    return jsonify({"ok": True})

# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, threaded=True)

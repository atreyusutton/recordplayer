#!/usr/bin/env bash
# onevent.sh — librespot event hook
# Called by librespot on every playback event.
# Writes /tmp/now_playing.json for display.py to pick up.
#
# Relevant env vars set by librespot:
#   PLAYER_EVENT  — started | changed | playing | paused | stopped | preloading | end_of_track
#   NAME          — track title
#   ARTISTS       — artist name(s)
#   ALBUM         — album name
#   COVERS        — space-separated CDN image URLs (largest first)
#   TRACK_ID      — Spotify track ID

OUT="/tmp/now_playing.json"

# Pick the first (largest) cover URL
COVER_URL=""
for url in $COVERS; do
    COVER_URL="$url"
    break
done

case "$PLAYER_EVENT" in
    playing|started|changed)
        # Escape quotes for JSON safety
        TITLE="${NAME//\"/\\\"}"
        ARTIST="${ARTISTS//\"/\\\"}"
        COVER="${COVER_URL//\"/\\\"}"

        printf '{\n  "event": "playing",\n  "title": "%s",\n  "artist": "%s",\n  "cover_url": "%s"\n}\n' \
            "$TITLE" "$ARTIST" "$COVER" > "$OUT"
        ;;

    paused)
        printf '{"event": "paused"}\n' > "$OUT"
        ;;

    stopped|end_of_track)
        printf '{"event": "stopped"}\n' > "$OUT"
        ;;

    # preloading, volume_set, etc. — ignore
    *)
        exit 0
        ;;
esac

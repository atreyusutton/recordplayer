#!/usr/bin/env bash
# librespot 0.8.0 onevent hook
# In librespot 0.8.0, track metadata (NAME/ARTISTS/COVERS) is only present
# on the `track_changed` event. The `playing` event fires separately without
# metadata, so we persist track info to a state file for pause/resume.
umask 022

OUT="/tmp/now_playing.json"
STATE="/tmp/now_playing_state.json"

# Pick first (largest) cover URL
COVER_URL=""
for url in $COVERS; do
    COVER_URL="$url"
    break
done

case "$PLAYER_EVENT" in
    track_changed)
        TITLE="${NAME//\"/\\\"}"
        ARTIST="${ARTISTS//\"/\\\"}"
        COVER="${COVER_URL//\"/\\\"}"
        # Persist track info for pause→resume
        printf '{"title":"%s","artist":"%s","cover_url":"%s"}\n' \
            "$TITLE" "$ARTIST" "$COVER" > "$STATE"
        # Write playing JSON immediately (track_changed always precedes playback)
        printf '{\n  "event": "playing",\n  "title": "%s",\n  "artist": "%s",\n  "cover_url": "%s"\n}\n' \
            "$TITLE" "$ARTIST" "$COVER" > "$OUT"
        ;;

    playing)
        # Fired on resume from pause — no metadata in this event.
        # Restore track info from saved state file.
        if [ -f "$STATE" ]; then
            python3 -c "
import json
s = json.load(open('$STATE'))
d = {'event': 'playing', 'title': s.get('title',''), 'artist': s.get('artist',''), 'cover_url': s.get('cover_url','')}
print(json.dumps(d, indent=2))
" > "$OUT" 2>/dev/null || printf '{"event":"playing"}\n' > "$OUT"
        fi
        ;;

    paused)
        printf '{"event":"paused"}\n' > "$OUT"
        ;;

    stopped|end_of_track|session_disconnected)
        printf '{"event":"stopped"}\n' > "$OUT"
        ;;

    *)
        exit 0
        ;;
esac

#!/usr/bin/env bash
# librespot 0.8.0 onevent hook
# In librespot 0.8.0, track metadata (NAME/ARTISTS/COVERS) is only present
# on the `track_changed` event. The `playing` event fires separately without
# metadata, so we persist track info to a state file for pause/resume.
#
# IMPORTANT: track_changed and playing fire nearly simultaneously as separate
# processes. We use flock to serialize them so `playing` always reads the
# STATE file that `track_changed` has already updated (not the old one).
umask 022

OUT="/tmp/now_playing.json"
STATE="/tmp/now_playing_state.json"
DEBUG_LOG="/tmp/onevent_debug.log"

# Serialize concurrent invocations — prevents the race where `playing` reads
# stale STATE before `track_changed` has finished writing it.
exec 9>/tmp/onevent.lock
flock -x -w 5 9 || exit 1

# Debug log: append event + key vars for every call (helps diagnose missing art)
{
    printf '\n[%s] PLAYER_EVENT=%s\n' "$(date -Iseconds)" "$PLAYER_EVENT"
    env | grep -E '^(NAME|ARTISTS|ALBUM|COVERS|TRACK_ID|DURATION_MS)=' | sort
} >> "$DEBUG_LOG" 2>/dev/null

# Build cover URL from $COVERS.
# librespot may provide full https:// URLs or bare image IDs depending on version.
COVER_URL=""
for token in $COVERS; do
    if [[ "$token" == http* ]]; then
        COVER_URL="$token"
    elif [[ -n "$token" ]]; then
        COVER_URL="https://i.scdn.co/image/$token"
    fi
    break
done

case "$PLAYER_EVENT" in
    track_changed)
        TITLE="${NAME//\"/\\\"}"
        ARTIST="${ARTISTS//\"/\\\"}"
        COVER="${COVER_URL//\"/\\\"}"
        # Persist track info for pause→resume (written before OUT so `playing`
        # always reads fresh data if it fires concurrently)
        printf '{"title":"%s","artist":"%s","cover_url":"%s"}\n' \
            "$TITLE" "$ARTIST" "$COVER" > "$STATE"
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

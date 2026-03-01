#!/usr/bin/env bash
# librespot 0.8.0 onevent hook
# In librespot 0.8.0, track metadata (NAME/ARTISTS/COVERS) is only present
# on the `track_changed` event. The `playing` event fires separately without
# metadata, so we persist track info to a state file for pause/resume.
#
# IMPORTANT: track_changed and playing fire nearly simultaneously as separate
# processes. We use flock to serialize them so `playing` always reads the
# STATE file that `track_changed` has already updated (not the old one).
#
# IMPORTANT: librespot separates multiple artists with newline characters in
# the ARTISTS env var. All JSON is written via python3 json.dumps to handle
# this and any other special characters correctly.
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
        # Use python3 json.dumps to write both STATE and OUT so that special
        # characters in NAME/ARTISTS (including the newlines librespot uses to
        # separate multiple artists) are properly escaped. Passing values via
        # env avoids any bash quoting issues.
        COVER_URL="$COVER_URL" python3 - "$STATE" "$OUT" << 'PYEOF' 2>>"$DEBUG_LOG"
import json, os, sys

title  = os.environ.get('NAME', '')
# librespot separates multiple artists with newlines — join them
artist = ', '.join(os.environ.get('ARTISTS', '').splitlines())
cover  = os.environ.get('COVER_URL', '')

state   = {'title': title, 'artist': artist, 'cover_url': cover}
playing = dict(state, event='playing')

with open(sys.argv[1], 'w') as f:
    f.write(json.dumps(state) + '\n')
with open(sys.argv[2], 'w') as f:
    f.write(json.dumps(playing, indent=2) + '\n')
PYEOF
        ;;

    playing)
        # Fired on resume from pause — no metadata in this event.
        # Restore track info from saved state file.
        if [ -f "$STATE" ]; then
            python3 - "$STATE" "$OUT" << 'PYEOF' 2>>"$DEBUG_LOG"
import json, sys

with open(sys.argv[1]) as f:
    state = json.load(f)

playing = dict(state, event='playing')

with open(sys.argv[2], 'w') as f:
    f.write(json.dumps(playing, indent=2) + '\n')
PYEOF
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

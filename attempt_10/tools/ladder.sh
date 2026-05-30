#!/bin/bash
# Launch the full P3 rung-ladder for one stage; all 3 rungs detached (setsid); dialogues -> per_repo_iter/<slug>/.
# Usage: ladder.sh <slug> <repo> <sha> <jv_from> <jv_to>
set -u
T=/home/vmihaylov/java_8_11_17_to_java_21/attempt_10
SLUG="$1"; REPO="$2"; SHA="$3"; JF="$4"; JT="$5"
OUT="$T/per_repo_iter/$SLUG"; mkdir -p "$OUT"
prep(){ rm -rf "$1" 2>/dev/null; git clone -q --depth 120 "https://github.com/$REPO" "$1" && ( cd "$1" && git fetch -q --depth 240 origin "$SHA" && git checkout -q "$SHA" ); }
# rung 1: opus (clones its own tree)
setsid bash "$T/tools/opus_rung.sh" "$SLUG" "$REPO" "$SHA" "$JF" "$JT" </dev/null >"/tmp/$SLUG.opus.out" 2>&1 &
# rung 2: qwen
QWD="/tmp/$SLUG.qwen"; prep "$QWD"
setsid env PATH="$HOME/bin:$PATH" python3 "$T/tools/middle_qwen.py" "$SLUG" "$QWD" "$JF" "$JT" </dev/null >"/tmp/$SLUG.qwen.out" 2>&1 &
# rung 3: oh_qwen
OWD="/tmp/$SLUG.oh"; prep "$OWD"
( cd /tmp && setsid env PATH="$HOME/bin:/tmp:$PATH" python3 /tmp/oh_one.py "$OWD" "$SLUG" </dev/null >"$OUT/dialogue.oh_qwen.log" 2>&1 & )
echo "ladder launched: $SLUG (opus+qwen+oh detached)"

#!/bin/bash
# D3 opus rung: deterministic prompt-flow on a stage (strongest-JDK mechanical run; judgment cases escalate to Claude+Opus).
# Preserves FULL dialogue to per_repo_iter/<slug>/dialogue.opus.log + trajectory.opus.json. Discovers nested project dir.
# Usage: opus_rung.sh <slug> <repo> <sha> <jv_from> <jv_to>
set -u
ATTEMPT=/home/vmihaylov/java_8_11_17_to_java_21/attempt_10
SLUG="$1"; REPO="$2"; SHA="$3"; JF="$4"; JT="$5"
OUT="$ATTEMPT/per_repo_iter/$SLUG"; WD="/tmp/${SLUG}_opus"
LOG="$OUT/dialogue.opus.log"
export PATH=$HOME/bin:$PATH
mkdir -p "$OUT"; rm -rf "$WD"
exec > >(tee "$LOG") 2>&1
echo "=== OPUS RUNG (deterministic prompt-flow) :: $SLUG ==="
echo "stage: $REPO @ $SHA  J${JF}->J${JT}  ts: $(date)"
echo
echo "### STEP 1: git baseline (clone @ sha)"
git clone --quiet --depth 120 https://github.com/$REPO "$WD" && cd "$WD" && git fetch --quiet --depth 240 origin "$SHA" && git checkout --quiet "$SHA"
git -c user.email=a@b.c -c user.name=opus add -A && git -c user.email=a@b.c -c user.name=opus commit -q -m baseline
echo "HEAD: $(git log --oneline -1)"
PROJ="$WD"
if [ ! -f "$WD/pom.xml" ]; then
  REL=$(cd "$WD" && find . -name pom.xml -not -path './.git/*' -printf '%d %p\n' 2>/dev/null | sort -n | head -1 | awk '{print $2}')
  [ -n "$REL" ] && PROJ="$WD/$(dirname "$REL")"
fi
cd "$PROJ"; echo "### project dir: $PROJ"
echo
echo "### STEP 2: baseline tests under JDK=$JF"
JDK=$JF mvn -B -ntp test 2>&1 | tail -50
python3 - "$PROJ" "$OUT/pre.json" <<'PYX'
import sys; sys.path.insert(0,'/home/vmihaylov/java_8_11_17_to_java_21/attempt_10/tools')
import d10_outer_persist as d, json
pre=d.surefire_counts(sys.argv[1]); json.dump(pre, open(sys.argv[2],'w'))
print("BASELINE_PASS:", pre['tests'],"tests",pre['failures'],"fail",pre['errors'],"err; passing=",len(pre['passing']))
PYX
echo
echo "### STEP 3: bump_${JF}_to_${JT}.sh ."
JDK=$JF bump_${JF}_to_${JT}.sh . 2>&1 | tail -80; echo "bump rc=${PIPESTATUS[0]}"
echo
echo "### STEP 4: compile under JDK=$JT"
JDK=$JT mvn -B -ntp compile 2>&1 | tail -40
echo
echo "### STEP 5: clear target, test under JDK=$JT"
docker run --rm --entrypoint bash -v "$PROJ":/work j21-fitness:latest -c "rm -rf /work/target" 2>/dev/null || rm -rf "$PROJ/target" 2>/dev/null
JDK=$JT mvn -B -ntp test 2>&1 | tail -50
echo
echo "### conclude: verdict (pom java version + test conservation)"
python3 - "$PROJ" "$OUT/pre.json" "$JT" "$LOG" "$OUT/trajectory.opus.json" "$SLUG" <<'PYX'
import sys, json; sys.path.insert(0,'/home/vmihaylov/java_8_11_17_to_java_21/attempt_10/tools')
import d10_outer_persist as d
proj, prep, jt, log, traj, slug = sys.argv[1:7]
pre=json.load(open(prep)); post=d.surefire_counts(proj); pom=d.pom_java_version(proj)
verdict=d.compute_verdict(pom, int(jt), pre, post, log)
json.dump({'stage':slug,'rung':'opus','verdict':verdict,'pom_java_version_post':pom,'project_dir':proj,
           'pre_passing':len(pre['passing']),'post_passing':len(post['passing']),'pre_counts':pre,'post_counts':post}, open(traj,'w'), indent=2)
print("VERDICT:", verdict, "pom_java=", pom)
PYX
echo "=== OPUS DONE ==="

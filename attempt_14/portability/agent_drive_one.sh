#!/bin/bash
# Unified per-repo driver for ALL THREE agents (opencode | kilo | openhands). Identical flow,
# skill, env, and scoring — the AGENT (6th arg) is the only variable. No force-apply.
# Args: REPO SHA FROM TO SLUG AGENT ; env: OC_KEY. Emits /out/$SLUG/result.json.
set -uo pipefail
REPO=$1; SHA=$2; FROM=$3; TO=$4; SLUG=$5; AGENT=$6
export HOME=/root
export OPENAI_API_KEY="$OC_KEY"; export QWEN_API_KEY="$OC_KEY"
QWEN_BASE="https://inference.mikhailov.tech/qwen-3.6-27b-fp8/v1"; QWEN_MODEL="qwen-3.6-27b-fp8"
OUT=/out/$SLUG; mkdir -p "$OUT"

emit() { python3 - "$@" <<'PY'
import sys, json
out, slug, repo, hop, verdict, pre, post, lost, prerc, postrc, comprc = sys.argv[1:12]
json.dump({"slug": slug, "repo": repo, "hop": hop, "verdict": verdict, "pre_pass": int(pre),
           "post_pass": int(post), "lost": int(lost), "prerc": int(prerc), "postrc": int(postrc),
           "compile_rc": int(comprc)}, open(out + "/result.json", "w"), indent=1)
print("VERDICT", verdict, "pre", pre, "post", post, "lost", lost)
PY
}
passet() { python3 - "$1" "$2" <<'PY'
import sys, glob, xml.etree.ElementTree as ET
root, dst = sys.argv[1], sys.argv[2]
s = set()
for x in glob.glob(root + "/**/target/surefire-reports/TEST-*.xml", recursive=True):
    try: r = ET.parse(x).getroot()
    except Exception: continue
    for tc in r.iter("testcase"):
        if not any(c.tag in ("failure", "error", "skipped") for c in tc):
            s.add(tc.get("classname", "") + "#" + tc.get("name", ""))
open(dst, "w").write("\n".join(sorted(s)))
print(len(s))
PY
}

cd /root; rm -rf work; mkdir work; cd work
git init -q; git config --global advice.detachedHead false
git config --global user.email a@b.c; git config --global user.name x
git remote add origin "https://github.com/$REPO.git"
if ! ( git fetch -q --depth 1 origin "$SHA" && git checkout -q FETCH_HEAD ); then
  emit "$OUT" "$SLUG" "$REPO" "$FROM->$TO" FETCH_FAIL 0 0 0 1 1 1; exit 0; fi
chmod +x ./mvnw 2>/dev/null || true
# opencode/kilo sandbox to the working dir and auto-reject reads of external dirs (e.g. /skill),
# so they cannot read SKILL.md / the failure table. Copy the skill INTO the workdir (read-only)
# so all three agents read it as a local path. (OpenHands isn't sandboxed, but this is harmless.)
cp -r /skill ./.bump-skill && chmod -R a-w ./.bump-skill

JAVA_HOME=/opt/jdk/$FROM mvn -B -ntp test -Dmaven.test.failure.ignore=true > "$OUT/pre.log" 2>&1 || true
PRE=$(passet "$(pwd)" "$OUT/pre_set.txt"); PRERC=0
find . -path '*/target/surefire-reports' -type d -exec rm -rf {} + 2>/dev/null || true

cat > AGENTS.md <<A
# How to bump this project's Java version
Use the bump-java-version skill in \`.bump-skill/\`: read \`.bump-skill/SKILL.md\`, a step-by-step manual you carry out YOURSELF. It uses only standard tools — JDKs, Maven, and OpenRewrite (recipes from Maven Central). There are NO bump scripts to run; perform each step in the manual by hand.
JDKs are at /opt/jdk/{8,11,17,21}; select one with JAVA_HOME. System Maven (\`mvn\`) is installed.
Baseline: \`JAVA_HOME=/opt/jdk/$FROM mvn -B -ntp test\` ; verify: \`JAVA_HOME=/opt/jdk/$TO mvn -B -ntp test\`.
A
PROMPT="Bump this Maven project from Java $FROM to Java $TO by following the bump-java-version manual in .bump-skill/SKILL.md. First read .bump-skill/SKILL.md in full. Then carry out its numbered steps YOURSELF with the standard tools (there are no bump scripts): establish the Java $FROM baseline, make Lombok safe, run the OpenRewrite migration command the manual gives for this hop, apply the deterministic pom edits it lists, then run the tests under Java $TO with JAVA_HOME=/opt/jdk/$TO mvn -B -ntp test and conserve every previously-passing test. If a step fails, find it in the manual's troubleshooting table, apply the listed fix, and re-run that step. Report the final test result."

# --- the ONLY agent-specific step ---
case "$AGENT" in
  opencode)
    mkdir -p /root/.config/opencode; cp /cfg/opencode.json /root/.config/opencode/opencode.json
    timeout 1800 opencode run -m qwen/$QWEN_MODEL "$PROMPT" > "$OUT/agent.log" 2>&1; echo "agent rc=$?" >> "$OUT/agent.log" ;;
  kilo|kilocode)
    mkdir -p /root/.config/kilo; cp /cfg/kilo.json /root/.config/kilo/opencode.json
    timeout 1800 kilo run -m qwen/$QWEN_MODEL "$PROMPT" > "$OUT/agent.log" 2>&1; echo "agent rc=$?" >> "$OUT/agent.log" ;;
  openhands)
    OC_BASE="$QWEN_BASE" OC_MODEL="$QWEN_MODEL" timeout 1800 /opt/ohvenv/bin/python /oh_run.py "$(pwd)" "$PROMPT" > "$OUT/agent.log" 2>&1; echo "agent rc=$?" >> "$OUT/agent.log" ;;
  *) echo "unknown agent $AGENT" > "$OUT/agent.log" ;;
esac

JAVA_HOME=/opt/jdk/$TO mvn -B -ntp -DskipTests compile > "$OUT/compile.log" 2>&1; COMPRC=$?
JAVA_HOME=/opt/jdk/$TO mvn -B -ntp test -Dmaven.test.failure.ignore=true > "$OUT/post.log" 2>&1; POSTRC=$?
POST=$(passet "$(pwd)" "$OUT/post_set.txt")
LOST=$(python3 - "$OUT/pre_set.txt" "$OUT/post_set.txt" <<'PY'
import sys
pre=set(open(sys.argv[1]).read().split("\n"))-{""}
post=set(open(sys.argv[2]).read().split("\n"))-{""}
print(len(pre-post))
PY
)
if [ "$PRE" -eq 0 ]; then V=NO_BASELINE
elif [ "$COMPRC" -ne 0 ]; then V=FAIL_build_post
elif [ "$LOST" -ne 0 ]; then V=FAIL_test_conservation
else V=PASS; fi
emit "$OUT" "$SLUG" "$REPO" "$FROM->$TO" "$V" "$PRE" "$POST" "$LOST" "$PRERC" "$POSTRC" "$COMPRC"

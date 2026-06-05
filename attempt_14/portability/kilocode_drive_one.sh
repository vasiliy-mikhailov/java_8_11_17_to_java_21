#!/bin/bash
# Container-side KILO CODE per-repo driver (runs INSIDE bump-kilocode-sweep:latest).
# Mirror of opencode_drive_one.sh; only the agent (kilo) + its config path differ.
# Args: REPO SHA FROM TO SLUG ; env: OC_KEY. Emits /out/$SLUG/result.json.
set -uo pipefail
REPO=$1; SHA=$2; FROM=$3; TO=$4; SLUG=$5
export HOME=/root
export OPENAI_API_KEY="$OC_KEY"; export QWEN_API_KEY="$OC_KEY"
mkdir -p /root/.config/kilo; cp /cfg/kilo.json /root/.config/kilo/opencode.json
OUT=/out/$SLUG; mkdir -p "$OUT"

emit() { python3 - "$@" <<'PY'
import sys, json
out, slug, repo, hop, verdict, pre, post, lost, prerc, postrc, comprc = sys.argv[1:12]
json.dump({"slug": slug, "repo": repo, "hop": hop, "verdict": verdict,
           "pre_pass": int(pre), "post_pass": int(post), "lost": int(lost),
           "prerc": int(prerc), "postrc": int(postrc), "compile_rc": int(comprc)},
          open(out + "/result.json", "w"), indent=1)
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

JAVA_HOME=/opt/jdk/$FROM mvn -B -ntp test -Dmaven.test.failure.ignore=true > "$OUT/pre.log" 2>&1 || true
PRE=$(passet "$(pwd)" "$OUT/pre_set.txt"); PRERC=0
find . -path '*/target/surefire-reports' -type d -exec rm -rf {} + 2>/dev/null || true

cat > AGENTS.md <<A
# How to bump this project's Java version
Use the bump-java-version skill at \`/skill\` (read \`/skill/SKILL.md\`).
To go from Java $FROM to Java $TO run: \`bash /skill/scripts/bump_${FROM}_to_${TO}.sh \$(pwd)\`
JDKs are at /opt/jdk/{8,11,17,21}; the scripts pick the JDK via JAVA_HOME. System Maven (\`mvn\`) is installed; select the JDK with JAVA_HOME.
Baseline: \`JAVA_HOME=/opt/jdk/$FROM mvn -B -ntp test\` ; verify: \`JAVA_HOME=/opt/jdk/$TO mvn -B -ntp test\`.
A

PROMPT="Bump this Maven project from Java $FROM to Java $TO using the bump-java-version skill in AGENTS.md and /skill/SKILL.md. Run bash /skill/scripts/bump_${FROM}_to_${TO}.sh $(pwd), then run the tests under Java $TO with JAVA_HOME=/opt/jdk/$TO mvn -B -ntp test and conserve every previously-passing test. If a step fails, consult the SKILL.md failure table and apply the listed fix. Report the final test result."
timeout 1800 kilo run -m qwen/qwen-3.6-27b-fp8 "$PROMPT" > "$OUT/kilo.log" 2>&1
echo "kilo exit=$?" >> "$OUT/kilo.log"

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

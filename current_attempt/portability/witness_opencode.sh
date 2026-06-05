#!/bin/bash
# Phase 2: opencode (third-party agent, Qwen FP8) drives the bump-java-version skill
# in the clean container. Args: REPO SHA FROM TO
REPO="$1"; SHA="$2"; FROM="$3"; TO="$4"
export HOME=/root
export OPENAI_API_KEY="$OC_KEY"; export QWEN_API_KEY="$OC_KEY"
mkdir -p /root/.config/opencode; cp /cfg/opencode.json /root/.config/opencode/opencode.json

# Skill installs its bundled recipe artifact (until on Maven Central).
M=/root/.m2/repository/tech/mikhailov/bump_java_version_recipes/bump-java-version-recipes/1.0.0
mkdir -p "$M"; cp /skill/recipe-artifact/*.jar "$M/"; cp /skill/recipe-artifact/*.pom "$M/bump-java-version-recipes-1.0.0.pom"

cd /root; rm -rf work; mkdir work; cd work
git init -q; git config --global advice.detachedHead false; git config --global user.email a@b.c; git config --global user.name x
git remote add origin "https://github.com/$REPO.git"
git fetch -q --depth 1 origin "$SHA" && git checkout -q FETCH_HEAD || { echo FETCHFAIL > /logs/diag.txt; exit 3; }
chmod +x ./mvnw 2>/dev/null || true

cat > AGENTS.md <<A
# How to bump this project's Java version

Use the **bump-java-version skill** at \`/skill\`:
- Read \`/skill/SKILL.md\` for guidance.
- Bump scripts are in \`/skill/scripts/\`. To go from Java $FROM to Java $TO run:
  \`bash /skill/scripts/bump_${FROM}_to_${TO}.sh \$(pwd)\`
- JDKs are at \`/opt/jdk/8\`, \`/opt/jdk/11\`, \`/opt/jdk/17\`, \`/opt/jdk/21\`. The scripts select the JDK via JAVA_HOME automatically (base \`/opt/jdk\`).
- There is NO system \`mvn\`; build and test with the project's \`./mvnw\`.
- Baseline test: \`JAVA_HOME=/opt/jdk/$FROM ./mvnw -B -ntp test\`
- After bumping, verify under the new JDK: \`JAVA_HOME=/opt/jdk/$TO ./mvnw -B -ntp test\`
A

{
  echo "--- DIAG ---"; echo "repo=$REPO from=$FROM to=$TO"; echo "mvn: $(which mvn || echo ABSENT)"
  echo "orig java.version: $(grep -hoE '<java.version>[^<]+' pom.xml | head -1)"
} > /logs/diag.txt

echo "--- DRIVE opencode (Qwen) ---" >> /logs/diag.txt
timeout 1500 opencode run -m qwen/qwen-3.6-27b-fp8 \
  "Bump this Maven project from Java $FROM to Java $TO using the bump-java-version skill described in AGENTS.md and /skill/SKILL.md. Run the appropriate bump script on the current directory ($(pwd)), then run the project's tests under Java $TO with ./mvnw and confirm they still pass. Report the final test result." \
  > /logs/opencode.log 2>&1
echo "opencode exit=$?" >> /logs/diag.txt
tail -40 /logs/opencode.log >> /logs/diag.txt

echo "--- VERIFY (independent post-test jdk$TO) ---" >> /logs/diag.txt
echo "java.version now: $(grep -hoE '<java.version>[^<]+' pom.xml | head -1)" >> /logs/diag.txt
JAVA_HOME=/opt/jdk/$TO ./mvnw -B -ntp test > /logs/post.log 2>&1
echo "post rc=$?" >> /logs/diag.txt
grep -E 'Tests run: [0-9]+, Fail|BUILD' /logs/post.log | tail -2 >> /logs/diag.txt
echo "PHASE2_DONE" >> /logs/diag.txt

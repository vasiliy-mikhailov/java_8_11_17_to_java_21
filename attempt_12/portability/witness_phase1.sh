#!/bin/bash
# Portability witness runner (P11). Args: REPO SHA FROM TO
# Runs INSIDE the clean bump-portability container. Logs to /logs.
REPO="$1"; SHA="$2"; FROM="$3"; TO="$4"
export HOME=/root
cd /tmp; rm -rf work; mkdir work; cd work
git init -q; git config --global advice.detachedHead false
git remote add origin "https://github.com/$REPO.git"
if ! (git fetch -q --depth 1 origin "$SHA" && git checkout -q FETCH_HEAD); then echo FETCHFAIL > /logs/diag.txt; exit 3; fi
chmod +x ./mvnw 2>/dev/null || true
{
  echo "--- DIAG $REPO $FROM->$TO ---"
  ls -la mvnw 2>&1 | head -1
  echo "orig versions: $(grep -hoE '<(java.version|maven.compiler.(release|target|source))>[^<]+' pom.xml | head -3 | tr '\n' ' ')"
  echo "which mvn: $(which mvn || echo ABSENT)"
  echo "MVN resolves: $([ -x ./mvnw ] && echo ./mvnw || echo mvn)"
} > /logs/diag.txt

# Skill installs its bundled recipe artifact (until it is on Maven Central).
M=/root/.m2/repository/tech/mikhailov/bump_java_version_recipes/bump-java-version-recipes/1.0.0
mkdir -p "$M"; cp /pskill/recipe-artifact/*.jar "$M/"; cp /pskill/recipe-artifact/*.pom "$M/bump-java-version-recipes-1.0.0.pom"

echo "--- BASELINE jdk$FROM ---" >> /logs/diag.txt
JAVA_HOME=/opt/jdk/$FROM ./mvnw -B -ntp test > /logs/pre.log 2>&1
echo "pre rc=$?" >> /logs/diag.txt
grep -E 'Tests run: [0-9]+, Fail|BUILD' /logs/pre.log | tail -2 >> /logs/diag.txt

echo "--- BUMP $FROM->$TO (portable skill) ---" >> /logs/diag.txt
bash /pskill/scripts/bump_${FROM}_to_${TO}.sh /tmp/work > /logs/bump.log 2>&1
echo "bump rc=$?" >> /logs/diag.txt
grep -E 'FAILED|\] OK|command not found|complete|compat|ERROR' /logs/bump.log | tail -14 >> /logs/diag.txt
echo "versions after bump: $(grep -hoE '<(java.version|maven.compiler.(release|target))>[^<]+' pom.xml | head -3 | tr '\n' ' ')" >> /logs/diag.txt

echo "--- POST jdk$TO ---" >> /logs/diag.txt
JAVA_HOME=/opt/jdk/$TO ./mvnw -B -ntp test > /logs/post.log 2>&1
echo "post rc=$?" >> /logs/diag.txt
grep -E 'Tests run: [0-9]+, Fail|BUILD' /logs/post.log | tail -2 >> /logs/diag.txt
echo "WITNESS_DONE" >> /logs/diag.txt

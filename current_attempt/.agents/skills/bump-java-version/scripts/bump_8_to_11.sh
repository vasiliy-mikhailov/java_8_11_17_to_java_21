#!/bin/bash
# bump_8_to_11.sh — OpenRewrite recipe sequence Java 8 → Java 11.
# Usage: ./bump_8_to_11.sh <workdir>
set -uo pipefail
WORK=${1:?usage: bump_8_to_11.sh <workdir>}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"   # resolve sibling scripts by path, not PATH (portability)
cd "$WORK"
# nested project: descend into the shallowest pom.xml dir if the workdir root has none
[ -f pom.xml ] || { _p=$(find . -maxdepth 6 -name pom.xml -not -path "*/target/*" -not -path "*/build/*" -not -path "*/.git/*" 2>/dev/null | awk -F/ "{print NF, \$0}" | sort -n | head -1 | cut -d" " -f2-); [ -n "$_p" ] && cd "$(dirname "$_p")"; }
_jh(){ local v="JAVA_HOME_$1"; printf "%s" "${!v:-${JDK_HOME_BASE:-/opt/jdk}/$1}"; }
MVN="${MVN:-$(command -v mvn >/dev/null 2>&1 && echo mvn || { [ -x ./mvnw ] && echo ./mvnw || echo mvn; })}"


COORDS="org.openrewrite.recipe:rewrite-migrate-java:3.35.0"
PLUGIN="org.openrewrite.maven:rewrite-maven-plugin:6.40.0"

# Write the compound lombok rewrite.yml INSIDE the workdir (so it's visible inside
# the mvn docker container at rewrite.yml).
LOMBOK_YML="$WORK/rewrite.yml"; LOMBOK_BAK="$WORK/.rewrite.yml.bumpbak"
[ -f "$LOMBOK_YML" ] && mv "$LOMBOK_YML" "$LOMBOK_BAK"
trap 'rm -f "$LOMBOK_YML"; [ -f "$LOMBOK_BAK" ] && mv "$LOMBOK_BAK" "$LOMBOK_YML"' EXIT
cat > "$LOMBOK_YML" <<'EOF'
type: specs.openrewrite.org/v1beta/recipe
name: smoke.bump.lombok_safe_bump
displayName: Lombok safe bump to 1.18.30
recipeList:
  - org.openrewrite.maven.UpgradeDependencyVersion:
      groupId: org.projectlombok
      artifactId: lombok
      newVersion: 1.18.30
  - org.openrewrite.maven.ChangePropertyValue: {key: lombok.version, newValue: '1.18.30'}
  - org.openrewrite.maven.ChangePropertyValue: {key: org.projectlombok.lombok.version, newValue: '1.18.30'}
  - org.openrewrite.maven.ChangePropertyValue: {key: lombok-version, newValue: '1.18.30'}
  - org.openrewrite.maven.ChangePropertyValue: {key: lombokVersion, newValue: '1.18.30'}
  - org.openrewrite.maven.ChangePropertyValue: {key: version.lombok, newValue: '1.18.30'}
EOF

run_recipe_yml() {
  local jdk=$1 yml=$2 label=$3 recipe_name=$4
  echo "=== [$label] JDK=$jdk yml=$yml" >&2
  JDK=$jdk JAVA_HOME="$(_jh $jdk)" $MVN -B -ntp -Denforcer.skip=true "$PLUGIN:run" \
    "-Drewrite.activeRecipes=$recipe_name" \
    "-Drewrite.recipeArtifactCoordinates=$COORDS"
  local rc=$?
  if [ $rc -ne 0 ]; then echo "=== [$label] FAILED rc=$rc" >&2; return $rc; fi
  echo "=== [$label] OK" >&2
}

run_recipe() {
  local jdk=$1 recipes=$2 label=$3
  echo "=== [$label] JDK=$jdk recipes=$recipes" >&2
  JDK=$jdk JAVA_HOME="$(_jh $jdk)" $MVN -B -ntp -Denforcer.skip=true "$PLUGIN:run" \
    "-Drewrite.activeRecipes=$recipes" \
    "-Drewrite.recipeArtifactCoordinates=$COORDS"
  local rc=$?
  if [ $rc -ne 0 ]; then echo "=== [$label] FAILED rc=$rc" >&2; return $rc; fi
  echo "=== [$label] OK" >&2
}

# the lombok recipe is the reactor-root rewrite.yml; OpenRewrite auto-discovers it for every module (no container-mount assumption).
run_recipe_yml 8 "rewrite.yml" lombok_safe_bump smoke.bump.lombok_safe_bump || exit $?
run_recipe 11 org.openrewrite.java.migrate.Java8toJava11 java8_to_java11 || exit $?
"$SCRIPT_DIR/java11_compat.sh" . || true

echo "=== bump_8_to_11 complete" >&2

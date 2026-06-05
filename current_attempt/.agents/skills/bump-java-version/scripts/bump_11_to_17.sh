#!/bin/bash
# bump_11_to_17.sh — OpenRewrite recipe sequence Java 11 → Java 17.
# Usage: ./bump_11_to_17.sh <workdir>
set -uo pipefail
WORK=${1:?usage: bump_11_to_17.sh <workdir>}
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"   # resolve sibling scripts by path
cd "$WORK"
# nested project: descend into the shallowest pom.xml dir if the workdir root has none
[ -f pom.xml ] || { _p=$(find . -maxdepth 6 -name pom.xml -not -path "*/target/*" -not -path "*/build/*" -not -path "*/.git/*" 2>/dev/null | awk -F/ "{print NF, \$0}" | sort -n | head -1 | cut -d" " -f2-); [ -n "$_p" ] && cd "$(dirname "$_p")"; }
_jh(){ local v="JAVA_HOME_$1"; printf "%s" "${!v:-${JDK_HOME_BASE:-/opt/jdk}/$1}"; }
MVN="${MVN:-$(command -v mvn >/dev/null 2>&1 && echo mvn || { [ -x ./mvnw ] && echo ./mvnw || echo mvn; })}"


COORDS="org.openrewrite.recipe:rewrite-migrate-java:3.35.0"
PLUGIN="org.openrewrite.maven:rewrite-maven-plugin:6.40.0"

# Workdir-local lombok safe-bump rewrite.yml (visible inside docker at rewrite.yml).
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
      overrideManagedVersion: true
  - org.openrewrite.maven.ChangePropertyValue: {key: lombok.version, newValue: '1.18.30'}
  - org.openrewrite.maven.ChangePropertyValue: {key: org.projectlombok.lombok.version, newValue: '1.18.30'}
  - org.openrewrite.maven.ChangePropertyValue: {key: lombok-version, newValue: '1.18.30'}
  - org.openrewrite.maven.ChangePropertyValue: {key: lombokVersion, newValue: '1.18.30'}
  - org.openrewrite.maven.ChangePropertyValue: {key: version.lombok, newValue: '1.18.30'}
EOF

run_recipe_yml() {
  local jdk=$1 yml=$2 label=$3 recipe_name=$4
  echo "=== [$label] JDK=$jdk yml=$yml" >&2
  JDK=$jdk JAVA_HOME="$(_jh $jdk)" $MVN -B -ntp "$PLUGIN:run" \
    "-Drewrite.activeRecipes=$recipe_name" \
    "-Drewrite.recipeArtifactCoordinates=$COORDS"
  local rc=$?
  if [ $rc -ne 0 ]; then echo "=== [$label] FAILED rc=$rc" >&2; return $rc; fi
  echo "=== [$label] OK" >&2
}

run_recipe() {
  local jdk=$1 recipes=$2 label=$3
  echo "=== [$label] JDK=$jdk recipes=$recipes" >&2
  local opts=""
  if [ "$jdk" = "17" ] || [ "$jdk" = "21" ]; then
    opts="--add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED --add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.io=ALL-UNNAMED --add-opens java.base/java.net=ALL-UNNAMED --add-opens java.base/java.nio=ALL-UNNAMED --add-opens java.base/java.nio.file=ALL-UNNAMED --add-opens java.base/java.text=ALL-UNNAMED --add-opens java.base/sun.nio.fs=ALL-UNNAMED --add-opens java.base/sun.nio.ch=ALL-UNNAMED --add-opens java.base/sun.net.dns=ALL-UNNAMED --add-opens java.base/sun.security.action=ALL-UNNAMED --add-opens java.base/sun.security.util=ALL-UNNAMED --add-opens java.base/sun.security.x509=ALL-UNNAMED --add-opens java.base/java.util.regex=ALL-UNNAMED --add-opens java.base/java.time=ALL-UNNAMED --add-opens java.desktop/java.awt.font=ALL-UNNAMED --add-opens java.desktop/java.awt=ALL-UNNAMED --add-opens java.desktop/sun.awt=ALL-UNNAMED --add-opens java.desktop/sun.font=ALL-UNNAMED --add-opens java.sql/java.sql=ALL-UNNAMED --add-opens java.xml/javax.xml.parsers=ALL-UNNAMED --add-opens java.xml/javax.xml.transform=ALL-UNNAMED --add-opens java.xml/javax.xml.transform.stream=ALL-UNNAMED --add-opens java.management/java.lang.management=ALL-UNNAMED --add-opens java.security.jgss/sun.security.jgss=ALL-UNNAMED --add-opens java.naming/com.sun.jndi.ldap=ALL-UNNAMED"
  fi
  JDK=$jdk JAVA_HOME="$(_jh $jdk)" MAVEN_OPTS="$opts" $MVN -B -ntp "$PLUGIN:run" \
    "-Drewrite.activeRecipes=$recipes" \
    "-Drewrite.recipeArtifactCoordinates=$COORDS"
  local rc=$?
  if [ $rc -ne 0 ]; then echo "=== [$label] FAILED rc=$rc" >&2; return $rc; fi
  echo "=== [$label] OK" >&2
}

# Old Lombok + javac17 also misbehaves on some symbols; safe-bump under jv_from before plugin/build17.
run_recipe_yml 11 "rewrite.yml" lombok_safe_bump smoke.bump.lombok_safe_bump || exit $?
run_recipe 11 org.openrewrite.java.migrate.UpgradePluginsForJava17 plugins17 || exit $?
run_recipe 17 org.openrewrite.java.migrate.UpgradeBuildToJava17 build17 || exit $?

"$SCRIPT_DIR/java17_compat.sh" . || true
echo "=== bump_11_to_17 complete" >&2

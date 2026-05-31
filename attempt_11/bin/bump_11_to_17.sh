#!/bin/bash
# bump_11_to_17.sh — OpenRewrite recipe sequence Java 11 → Java 17.
# Usage: ./bump_11_to_17.sh <workdir>
set -uo pipefail
WORK=${1:?usage: bump_11_to_17.sh <workdir>}
cd "$WORK"

COORDS="org.openrewrite.recipe:rewrite-migrate-java:3.35.0,tech.mikhailov.bump_java_version_recipes:bump-java-version-recipes:1.0.0"
PLUGIN="org.openrewrite.maven:rewrite-maven-plugin:6.40.0"

# Workdir-local lombok safe-bump rewrite.yml (visible inside docker at /work/src/.bump_lombok.yml).
LOMBOK_YML="$WORK/.bump_lombok.yml"
trap "rm -f $LOMBOK_YML" EXIT
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
  JDK=$jdk mvn -B -ntp "$PLUGIN:run" \
    "-Drewrite.activeRecipes=$recipe_name" \
    "-Drewrite.configLocation=$yml" \
    "-Drewrite.recipeArtifactCoordinates=$COORDS"
  local rc=$?
  if [ $rc -ne 0 ]; then echo "=== [$label] FAILED rc=$rc" >&2; return $rc; fi
  echo "=== [$label] OK" >&2
}

run_recipe() {
  local jdk=$1 recipes=$2 label=$3
  echo "=== [$label] JDK=$jdk recipes=$recipes" >&2
  JDK=$jdk mvn -B -ntp "$PLUGIN:run" \
    "-Drewrite.activeRecipes=$recipes" \
    "-Drewrite.recipeArtifactCoordinates=$COORDS"
  local rc=$?
  if [ $rc -ne 0 ]; then echo "=== [$label] FAILED rc=$rc" >&2; return $rc; fi
  echo "=== [$label] OK" >&2
}

# Old Lombok + javac17 also misbehaves on some symbols; safe-bump under jv_from before plugin/build17.
run_recipe_yml 11 ".bump_lombok.yml" lombok_safe_bump smoke.bump.lombok_safe_bump || exit $?
run_recipe 11 org.openrewrite.java.migrate.UpgradePluginsForJava17 plugins17 || exit $?
run_recipe 17 org.openrewrite.java.migrate.UpgradeBuildToJava17 build17 || exit $?

echo "=== bump_11_to_17 complete" >&2

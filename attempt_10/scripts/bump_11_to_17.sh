#!/bin/bash
# bump_11_to_17.sh — OpenRewrite recipe sequence Java 11 → Java 17.
# Usage: ./bump_11_to_17.sh <workdir>
set -uo pipefail
WORK=${1:?usage: bump_11_to_17.sh <workdir>}
cd "$WORK"

COORDS="org.openrewrite.recipe:rewrite-migrate-java:3.35.0,com.claude.recipes:claude-recipes:1.0.0"
PLUGIN="org.openrewrite.maven:rewrite-maven-plugin:6.40.0"

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

run_recipe 11 org.openrewrite.java.migrate.UpgradePluginsForJava17 plugins17 || exit $?
run_recipe 17 org.openrewrite.java.migrate.UpgradeBuildToJava17 build17 || exit $?

echo "=== bump_11_to_17 complete" >&2

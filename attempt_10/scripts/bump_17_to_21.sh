#!/bin/bash
# bump_17_to_21.sh — OpenRewrite recipe sequence that takes a Maven project from Java 17 to Java 21.
# Usage: ./bump_17_to_21.sh <workdir>
# Returns rc=0 on success of every step; non-zero on first failure.
# Caller is responsible for git baseline + post-build verification + test conservation.
set -uo pipefail
WORK=${1:?usage: bump_17_to_21.sh <workdir>}
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
  if [ $rc -ne 0 ]; then
    echo "=== [$label] FAILED rc=$rc" >&2
    return $rc
  fi
  echo "=== [$label] OK" >&2
}

run_recipe 17 org.openrewrite.java.migrate.UpgradePluginsForJava21 plugins21 || exit $?
run_recipe 21 org.openrewrite.java.migrate.UpgradeBuildToJava21 build21 || exit $?
run_recipe 21 \
  'org.openrewrite.java.migrate.RemoveIllegalSemicolons,org.openrewrite.java.migrate.lang.ThreadStopUnsupported,org.openrewrite.java.migrate.net.URLConstructorToURICreate,org.openrewrite.java.migrate.util.SequencedCollection,org.openrewrite.java.migrate.util.UseLocaleOf,org.openrewrite.staticanalysis.ReplaceDeprecatedRuntimeExecMethods,org.openrewrite.java.migrate.DeleteDeprecatedFinalize,org.openrewrite.java.migrate.RemovedSubjectMethods' \
  transforms21 || exit $?

echo "=== bump_17_to_21 complete" >&2

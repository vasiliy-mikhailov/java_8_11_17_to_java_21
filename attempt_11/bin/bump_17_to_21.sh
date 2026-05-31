#!/bin/bash
# bump_17_to_21.sh — OpenRewrite recipe sequence that takes a Maven project from Java 17 to Java 21.
# Usage: ./bump_17_to_21.sh <workdir>
# Returns rc=0 on success of every step; non-zero on first failure.
# Caller is responsible for git baseline + post-build verification + test conservation.
set -uo pipefail
WORK=${1:?usage: bump_17_to_21.sh <workdir>}
cd "$WORK"

COORDS="org.openrewrite.recipe:rewrite-migrate-java:3.35.0,tech.mikhailov.bump_java_version_recipes:bump-java-version-recipes:1.0.0"
PLUGIN="org.openrewrite.maven:rewrite-maven-plugin:6.40.0"

# Write the compound lombok rewrite.yml INSIDE the workdir so it's visible inside
# the mvn docker container at /work/src/.bump_lombok.yml.
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
  if [ $rc -ne 0 ]; then
    echo "=== [$label] FAILED rc=$rc" >&2
    return $rc
  fi
  echo "=== [$label] OK" >&2
}

# Lombok 1.18.<29 + javac21 = NoSuchFieldError JCTree$JCImport.qualid.
# Run the lombok safe bump under JDK=17 (jv_from) BEFORE switching to JDK 21.
run_recipe_yml 17 "/work/src/.bump_lombok.yml" lombok_safe_bump smoke.bump.lombok_safe_bump || exit $?
run_recipe 17 org.openrewrite.java.migrate.UpgradePluginsForJava21 plugins21 || exit $?
run_recipe 21 org.openrewrite.java.migrate.UpgradeBuildToJava21 build21 || exit $?
run_recipe 21 \
  'org.openrewrite.java.migrate.RemoveIllegalSemicolons,org.openrewrite.java.migrate.lang.ThreadStopUnsupported,org.openrewrite.java.migrate.net.URLConstructorToURICreate,org.openrewrite.java.migrate.util.SequencedCollection,org.openrewrite.java.migrate.util.UseLocaleOf,org.openrewrite.staticanalysis.ReplaceDeprecatedRuntimeExecMethods,org.openrewrite.java.migrate.DeleteDeprecatedFinalize,org.openrewrite.java.migrate.RemovedSubjectMethods' \
  transforms21 || exit $?

echo "=== bump_17_to_21 complete" >&2

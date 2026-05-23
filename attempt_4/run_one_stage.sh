#!/usr/bin/env bash
# Single-stage container entrypoint.
# Expects the working tree already bind-mounted at /work/src (cloned + checked out
# by the host orchestrator). All this script does is switch JDK + apply ONE
# OpenRewrite recipe + return.
#
# Inputs (env):
#   STAGE_JDK        8 | 11 | 17 | 21 — which /opt/jdk/<n> to use for this stage
#   STAGE_RECIPE     /recipes/stage_N.yml — bind-mounted YAML composite recipe
#   STAGE_LOG        /out/stage_<n>.log — where to append run output
#   BUILD_TOOL       maven | gradle
#   PHASE            recipe | build_pre | build_post — what to do this invocation
set -uo pipefail
: "${STAGE_JDK:?}" "${BUILD_TOOL:?}" "${STAGE_LOG:?}" "${PHASE:?}"

export JAVA_HOME="/opt/jdk/$STAGE_JDK"
export PATH="$JAVA_HOME/bin:/opt/maven/bin:/opt/gradle/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

cd /work/src
# find project root
if [ -f pom.xml ] || [ -f build.gradle ] || [ -f build.gradle.kts ]; then
  PROJECT_ROOT="/work/src"
else
  parent_pom=$(find . -maxdepth 4 -name pom.xml \
    -exec grep -l -m1 '<modules>' {} + 2>/dev/null | \
    awk -F/ '{print NF, $0}' | sort -n | head -1 | cut -d" " -f2-)
  PROJECT_ROOT="/work/src/$(dirname "$parent_pom" 2>/dev/null)"
fi
cd "$PROJECT_ROOT"

MVN_FLAGS="-B -ntp -fae -Denforcer.skip=true -DskipTests -Dlombok.version=1.18.36 -Dmaven.javadoc.skip=true -Dcheckstyle.skip=true -Dspotbugs.skip=true -Dspring-boot.repackage.skip=true -Ddockerfile.skip=true -Dspring-javaformat.skip=true -Dformat.skip=true"

case "$PHASE" in
  build_pre|build_post)
    extra=""
    [ "$PHASE" = "build_post" ] && extra="-Dmaven.compiler.release=21 -Djava.version=21"
    echo "[$(date +%H:%M:%S)] $PHASE under JDK $STAGE_JDK" >> "$STAGE_LOG"
    if [ "$BUILD_TOOL" = "maven" ]; then
      mvn $MVN_FLAGS $extra -q compile >> "$STAGE_LOG" 2>&1
    else
      ./gradlew --no-daemon -q -x test compileJava >> "$STAGE_LOG" 2>&1 || \
        gradle --no-daemon -q -x test compileJava >> "$STAGE_LOG" 2>&1
    fi
    exit $?
    ;;
  recipe)
    : "${STAGE_RECIPE:?}"
    echo "[$(date +%H:%M:%S)] recipe $STAGE_RECIPE under JDK $STAGE_JDK" >> "$STAGE_LOG"
    PLUGIN=org.openrewrite.maven:rewrite-maven-plugin:6.12.0
    COORDS=org.openrewrite.recipe:rewrite-migrate-java:3.12.0,org.openrewrite.recipe:rewrite-spring:6.9.0,org.openrewrite.recipe:rewrite-testing-frameworks:3.11.0,org.openrewrite.recipe:rewrite-hibernate:2.9.0
    recipe_name=$(grep -E '^name:' "$STAGE_RECIPE" | head -1 | awk '{print $2}')
    if [ "$BUILD_TOOL" = "maven" ]; then
      mvn $MVN_FLAGS -U "$PLUGIN:run" \
          -Drewrite.activeRecipes="$recipe_name" \
          -Drewrite.configLocation="$STAGE_RECIPE" \
          -Drewrite.recipeArtifactCoordinates="$COORDS" \
          -Drewrite.failOnInvalidActiveRecipes=true \
          >> "$STAGE_LOG" 2>&1
      exit $?
    else
      echo "gradle staged recipe NYI" >> "$STAGE_LOG"
      exit 255
    fi
    ;;
  *)
    echo "unknown PHASE=$PHASE" >> "$STAGE_LOG"
    exit 1
    ;;
esac

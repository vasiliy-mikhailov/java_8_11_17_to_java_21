#!/usr/bin/env bash
# attempt_6 version of run_one_stage.sh with smarter project-root detection.
# Inputs (env):
#   STAGE_JDK        8 | 11 | 17 | 21
#   STAGE_RECIPE     /recipes/stage.yml (for PHASE=recipe)
#   STAGE_LOG        /out/stage.log
#   BUILD_TOOL       maven | gradle
#   PHASE            recipe | build_pre | build_post
set -uo pipefail
: "${STAGE_JDK:?}" "${BUILD_TOOL:?}" "${STAGE_LOG:?}" "${PHASE:?}"

export JAVA_HOME="/opt/jdk/$STAGE_JDK"
export PATH="$JAVA_HOME/bin:/opt/maven/bin:/opt/gradle/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

cd /work/src

# Project root: shallowest pom.xml (skipping common build outputs)
if [ -f pom.xml ]; then
  PROJECT_ROOT="/work/src"
elif [ -f build.gradle ] || [ -f build.gradle.kts ]; then
  PROJECT_ROOT="/work/src"
else
  # Find shallowest pom.xml that isn't inside target/build/node_modules
  candidate=$(find . -maxdepth 5 -name pom.xml \
    -not -path "*/target/*" -not -path "*/build/*" \
    -not -path "*/node_modules/*" -not -path "*/.git/*" 2>/dev/null | \
    awk -F/ '{print NF, $0}' | sort -n | head -1 | cut -d" " -f2-)
  if [ -n "$candidate" ]; then
    PROJECT_ROOT="/work/src/$(dirname "$candidate")"
  else
    # Try gradle in subdir
    candidate=$(find . -maxdepth 5 \( -name build.gradle -o -name build.gradle.kts \) \
      -not -path "*/build/*" -not -path "*/.git/*" 2>/dev/null | \
      awk -F/ '{print NF, $0}' | sort -n | head -1 | cut -d" " -f2-)
    PROJECT_ROOT="/work/src/$(dirname "${candidate:-.}")"
  fi
fi
echo "[$(date +%H:%M:%S)] PROJECT_ROOT=$PROJECT_ROOT PHASE=$PHASE JDK=$STAGE_JDK" >> "$STAGE_LOG"
cd "$PROJECT_ROOT" || { echo "cd failed" >> "$STAGE_LOG"; exit 2; }

MVN_FLAGS="-B -ntp -fae -Denforcer.skip=true -DskipTests -Dlombok.version=1.18.36 -Dmaven.javadoc.skip=true -Dcheckstyle.skip=true -Dspotbugs.skip=true -Dspring-boot.repackage.skip=true -Ddockerfile.skip=true -Dspring-javaformat.skip=true -Dformat.skip=true"

case "$PHASE" in
  build_pre|build_post)
    extra=""
    if [ "$PHASE" = "build_post" ]; then
      # JDK 8 javac does not support --release (added in JDK 9). Use source/target instead.
      if [ "$STAGE_JDK" -lt 9 ]; then
        extra="-Dmaven.compiler.source=${STAGE_JDK} -Dmaven.compiler.target=${STAGE_JDK}"
      else
        extra="-Dmaven.compiler.release=${STAGE_JDK}"
      fi
    fi
    if [ "$BUILD_TOOL" = "maven" ]; then
      mvn $MVN_FLAGS $extra -q compile >> "$STAGE_LOG" 2>&1
    else
      ./gradlew --no-daemon -q -x test compileJava >> "$STAGE_LOG" 2>&1 || \
        gradle --no-daemon -q -x test compileJava >> "$STAGE_LOG" 2>&1
    fi
    exit $?
    ;;
  test_pre|test_post)
    # mvn test under JDK = STAGE_JDK. -DskipTests stripped via override to false. Other -D*.skip kept.
    # test_pre runs against UNMODIFIED source under jv_from; test_post runs against post-recipe source under jv_to.
    extra="-DskipTests=false"
    if [ "$PHASE" = "test_post" ]; then
      if [ "$STAGE_JDK" -lt 9 ]; then
        extra="-Dmaven.compiler.source=${STAGE_JDK} -Dmaven.compiler.target=${STAGE_JDK} -DskipTests=false"
      else
        extra="-Dmaven.compiler.release=${STAGE_JDK} -DskipTests=false"
      fi
    fi
    if [ "$BUILD_TOOL" = "maven" ]; then
      mvn $MVN_FLAGS $extra -q test >> "$STAGE_LOG" 2>&1
    else
      ./gradlew --no-daemon -q test >> "$STAGE_LOG" 2>&1 || \
        gradle --no-daemon -q test >> "$STAGE_LOG" 2>&1
    fi
    exit $?
    ;;
  recipe)
    : "${STAGE_RECIPE:?}"
    PLUGIN=org.openrewrite.maven:rewrite-maven-plugin:6.40.0
    COORDS=org.openrewrite.recipe:rewrite-migrate-java:3.35.0,org.openrewrite.recipe:rewrite-spring:6.31.0,org.openrewrite.recipe:rewrite-testing-frameworks:3.36.0,org.openrewrite.recipe:rewrite-hibernate:2.20.3,com.claude.recipes:claude-recipes:1.0.0
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
      echo "gradle recipe NYI" >> "$STAGE_LOG"
      exit 255
    fi
    ;;
  *)
    echo "unknown PHASE=$PHASE" >> "$STAGE_LOG"
    exit 1
    ;;
esac

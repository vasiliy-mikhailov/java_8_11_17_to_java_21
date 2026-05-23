#!/usr/bin/env bash
# Staged container entrypoint for attempt_4.
# Inputs (env):
#   REPO_URL, REPO_SHA, REPO_ID    repo to evaluate
#   JAVA_VERSION                   8 | 11 | 17 — original source level (baseline)
#   BUILD_TOOL                     maven | gradle
#   STAGES                         comma-separated, ordered list of "jdk:recipe_file"
#                                  e.g. "11:/recipe/stage1.yml,17:/recipe/stage2.yml,21:/recipe/stage3.yml"
#   OUT_DIR                        bind-mounted; we write metrics.json + per-stage logs here
#
# Behaviour:
#   1. clone + checkout
#   2. for each stage in STAGES: switch JAVA_HOME, run OpenRewrite, optional verify
#   3. final mvn compile under JDK 21 — that's the build_post number
set -uo pipefail
for v in REPO_URL REPO_SHA REPO_ID JAVA_VERSION BUILD_TOOL STAGES OUT_DIR; do
  : "${!v:?missing env $v}"
done

mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/run.log"
METRICS="$OUT_DIR/metrics.json"
: > "$LOG"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG" >&2; }

# Per-stage outcomes
declare -a stage_names=()
declare -a stage_jdks=()
declare -a stage_rcs=()
declare -a stage_elapsed=()
build_pre=0
build_post=0
recipe_rc_final=-1
failure=""

write_metrics() {
  # Compose JSON manually — jq array building is verbose
  local stages_json="["
  local n=${#stage_names[@]}
  for ((i=0; i<n; i++)); do
    [ $i -gt 0 ] && stages_json+=","
    stages_json+="{\"name\":\"${stage_names[$i]}\",\"jdk\":${stage_jdks[$i]},\"rc\":${stage_rcs[$i]},\"elapsed_s\":${stage_elapsed[$i]}}"
  done
  stages_json+="]"
  cat > "$METRICS" <<JSON
{
  "repo_id": "$REPO_ID",
  "repo_url": "$REPO_URL",
  "sha": "$REPO_SHA",
  "java_version": $JAVA_VERSION,
  "build_tool": "$BUILD_TOOL",
  "build_pre": $build_pre,
  "build_post": $build_post,
  "recipe_rc_final": $recipe_rc_final,
  "failure": "$failure",
  "stages": $stages_json
}
JSON
}
trap write_metrics EXIT

# --- clone ---
log "clone $REPO_URL @ $REPO_SHA"
git clone --filter=blob:none --no-checkout "$REPO_URL" /work/src >>"$LOG" 2>&1 || { failure="clone"; exit 1; }
cd /work/src
git fetch --depth 50 origin "$REPO_SHA" >>"$LOG" 2>&1 || true
git checkout --detach "$REPO_SHA" >>"$LOG" 2>&1 || { failure="checkout"; exit 1; }

# --- find project root ---
if [ -f pom.xml ] || [ -f build.gradle ] || [ -f build.gradle.kts ]; then
  PROJECT_ROOT="/work/src"
else
  parent_pom=$(find . -maxdepth 4 -name pom.xml \
    -exec grep -l -m1 '<modules>' {} + 2>/dev/null | \
    awk -F/ '{print NF, $0}' | sort -n | head -1 | cut -d" " -f2-)
  PROJECT_ROOT="/work/src/$(dirname "$parent_pom")"
fi
log "project root: $PROJECT_ROOT"
cd "$PROJECT_ROOT"

# --- baseline build under declared JDK ---
export JAVA_HOME="/opt/jdk/$JAVA_VERSION"
export PATH="$JAVA_HOME/bin:/opt/maven/bin:/opt/gradle/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
MVN_FLAGS="-B -ntp -fae -Denforcer.skip=true -DskipTests -Dlombok.version=1.18.36 -Dmaven.javadoc.skip=true -Dcheckstyle.skip=true -Dspotbugs.skip=true -Dspring-boot.repackage.skip=true -Ddockerfile.skip=true -Dspring-javaformat.skip=true -Dformat.skip=true"
if [ "$BUILD_TOOL" = "maven" ]; then
  if mvn $MVN_FLAGS -q compile >>"$LOG" 2>&1; then build_pre=1; fi
else
  if ./gradlew --no-daemon -q -x test compileJava >>"$LOG" 2>&1 || gradle --no-daemon -q -x test compileJava >>"$LOG" 2>&1; then build_pre=1; fi
fi
log "baseline build_pre=$build_pre under JDK $JAVA_VERSION"

# --- iterate stages ---
PLUGIN=org.openrewrite.maven:rewrite-maven-plugin:6.12.0
COORDS=org.openrewrite.recipe:rewrite-migrate-java:3.12.0,org.openrewrite.recipe:rewrite-spring:6.9.0,org.openrewrite.recipe:rewrite-testing-frameworks:3.11.0,org.openrewrite.recipe:rewrite-hibernate:2.9.0

IFS=',' read -ra STAGE_LIST <<< "$STAGES"
for stage_spec in "${STAGE_LIST[@]}"; do
  jdk="${stage_spec%%:*}"
  recipe_path="${stage_spec#*:}"
  stage_name="stage_jdk${jdk}"
  log "=== $stage_name :: $recipe_path ==="
  export JAVA_HOME="/opt/jdk/$jdk"
  export PATH="$JAVA_HOME/bin:/opt/maven/bin:/opt/gradle/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
  recipe_name=$(grep -E '^name:' "$recipe_path" | head -1 | awk '{print $2}')
  log "recipe_name: $recipe_name"

  t0=$(date +%s)
  if [ "$BUILD_TOOL" = "maven" ]; then
    mvn $MVN_FLAGS -U "$PLUGIN:run" \
        -Drewrite.activeRecipes="$recipe_name" \
        -Drewrite.configLocation="$recipe_path" \
        -Drewrite.recipeArtifactCoordinates="$COORDS" \
        -Drewrite.failOnInvalidActiveRecipes=true \
        >>"$LOG" 2>&1
    rc=$?
  else
    rc=255  # gradle staged path not implemented yet
    log "gradle staged path NYI"
  fi
  t1=$(date +%s)
  elapsed=$((t1 - t0))
  stage_names+=("$stage_name")
  stage_jdks+=("$jdk")
  stage_rcs+=("$rc")
  stage_elapsed+=("$elapsed")
  recipe_rc_final=$rc
  log "$stage_name rc=$rc elapsed=${elapsed}s"
  if [ $rc -ne 0 ]; then
    failure="$stage_name"
    # Continue anyway — partial migration may still build_post
  fi
done

# --- final build under JDK 21 ---
export JAVA_HOME="/opt/jdk/21"
export PATH="$JAVA_HOME/bin:/opt/maven/bin:/opt/gradle/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
log "final build under JDK 21"
if [ "$BUILD_TOOL" = "maven" ]; then
  if mvn $MVN_FLAGS -q -Dmaven.compiler.release=21 -Djava.version=21 compile >>"$LOG" 2>&1; then build_post=1; fi
else
  if ./gradlew --no-daemon -q -x test compileJava >>"$LOG" 2>&1 || gradle --no-daemon -q -x test compileJava >>"$LOG" 2>&1; then build_post=1; fi
fi
log "build_post=$build_post"

# --- diff capture ---
git -C "$PROJECT_ROOT" diff > "$OUT_DIR/diff.patch" 2>/dev/null || true

#!/usr/bin/env bash
# Container entrypoint: clone repo, apply candidate recipe via OpenRewrite,
# attempt Java-21 build + tests, emit metrics + per-recipe data table.
#
# Env in:
#   REPO_URL, REPO_SHA, REPO_ID    repo to evaluate
#   JAVA_VERSION                   8 | 11 | 17 (source level for baseline)
#   BUILD_TOOL                     maven | gradle
#   RECIPE_NAME                    name of the composite in rewrite.yml
#   RECIPE_YML_PATH                bind-mounted rewrite.yml
#   OUT_DIR                        bind-mounted dir; we write metrics.json,
#                                  per_recipe.csv, run.log here
#
# Out (in OUT_DIR):
#   metrics.json     {repo_id, build_pre, build_post, tests_passed_post,
#                     tests_total_post, recipe_applied, recipe_rc,
#                     recipe_elapsed_s, build_elapsed_s, test_elapsed_s}
#   per_recipe.csv   OpenRewrite SourcesFileResults: recipe -> file -> change

set -uo pipefail
for v in REPO_URL REPO_SHA REPO_ID JAVA_VERSION BUILD_TOOL RECIPE_NAME RECIPE_YML_PATH OUT_DIR; do
  : "${!v:?missing env $v}"
done

mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/run.log"
METRICS="$OUT_DIR/metrics.json"
: > "$LOG"
log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG" >&2; }

# default metrics — overwritten by the phases below
build_pre=0; build_post=0; tests_post=0; tests_total_post=0
recipe_applied=0; recipe_rc=-1
recipe_elapsed=0; build_elapsed=0; test_elapsed=0
phase="init"; failure=""

write_metrics() {
  jq -n \
    --arg id "$REPO_ID" --arg url "$REPO_URL" --arg sha "$REPO_SHA" \
    --arg bt "$BUILD_TOOL" --arg phase "$phase" --arg failure "$failure" \
    --argjson jv "$JAVA_VERSION" \
    --argjson bp "$build_pre" --argjson bpo "$build_post" \
    --argjson tp "$tests_post" --argjson tt "$tests_total_post" \
    --argjson ra "$recipe_applied" --argjson rc "$recipe_rc" \
    --argjson re "$recipe_elapsed" --argjson be "$build_elapsed" --argjson te "$test_elapsed" \
    '{repo_id:$id, repo_url:$url, sha:$sha, java_version:$jv, build_tool:$bt,
      phase_reached:$phase, failure:$failure,
      build_pre:$bp, build_post:$bpo,
      tests_passed_post:$tp, tests_total_post:$tt,
      recipe_applied:$ra, recipe_rc:$rc,
      recipe_elapsed_s:$re, build_elapsed_s:$be, test_elapsed_s:$te}' \
    > "$METRICS"
}
trap write_metrics EXIT

# JDK 21 for everything. JDK 21 javac accepts --release N for N>=6, so
# even if the project pom asks for older source levels we can compile.
export JAVA_HOME="/opt/jdk/21"
export PATH="$JAVA_HOME/bin:$PATH"

# --- clone ---
phase="clone"
log "clone $REPO_URL @ $REPO_SHA"
git clone --filter=blob:none --no-checkout "$REPO_URL" /work/src >>"$LOG" 2>&1 || { failure="clone"; exit 1; }
cd /work/src
git fetch --depth 50 origin "$REPO_SHA" >>"$LOG" 2>&1 || true
git checkout --detach "$REPO_SHA" >>"$LOG" 2>&1 || { failure="checkout"; exit 1; }

# --- find the project root ---
# Preference order:
#   1. /work/src has a pom.xml or build.gradle
#   2. The pom.xml with <modules> declarations (multi-module parent)
#   3. The shallowest pom.xml / build.gradle
phase="project-root"
if [ -f pom.xml ] || [ -f build.gradle ] || [ -f build.gradle.kts ]; then
  PROJECT_ROOT="/work/src"
else
  parent_pom=$(find . -maxdepth 4 -name pom.xml \
    -exec grep -l -m1 '<modules>' {} + 2>/dev/null | \
    awk -F/ '{print NF, $0}' | sort -n | head -1 | cut -d" " -f2-)
  if [ -n "$parent_pom" ]; then
    PROJECT_ROOT=$(dirname "/work/src/$parent_pom" | sed 's|^/work/src/\./|/work/src/|')
  else
    build_file=$(find . -maxdepth 4 \( -name pom.xml -o -name build.gradle -o -name build.gradle.kts \) | \
      awk -F/ '{print NF, $0}' | sort -n | head -1 | cut -d" " -f2-)
    if [ -z "$build_file" ]; then
      failure="no-project-root"; exit 0
    fi
    PROJECT_ROOT=$(dirname "/work/src/$build_file" | sed 's|^/work/src/\./|/work/src/|')
  fi
  log "project root discovered at $PROJECT_ROOT"
fi
cd "$PROJECT_ROOT"

# Maven flags that defuse the common JDK-21 stumbling blocks across the corpus:
#   -Denforcer.skip=true     bypasses RequireJavaVersion rules pinned to 1.8/11
#   -Dlombok.version=1.18.36 overrides old Lombok that crashes with IllegalAccessError on JDK 21
#   -Dmaven.javadoc.skip=true skips javadoc which often references removed sun.* APIs
#   -Dskip.checkstyle=true   skips checkstyle which has its own JDK gripes
#   -fae                     keep going on per-module failures (-fail-at-end) for multi-module repos
MVN_OPTS_COMPAT="-fae -Denforcer.skip=true -Dlombok.version=1.18.36 -Dmaven.javadoc.skip=true -Dcheckstyle.skip=true -Dspotbugs.skip=true"

# --- pre-recipe baseline (on JDK 21) ---
phase="baseline"
t0=$(date +%s)
if [ "$BUILD_TOOL" = "maven" ]; then
  if mvn -B -q -DskipTests -ntp $MVN_OPTS_COMPAT package >>"$LOG" 2>&1; then build_pre=1; fi
else
  if ./gradlew --no-daemon -q assemble >>"$LOG" 2>&1; then build_pre=1; fi
fi
log "baseline build_pre=$build_pre"

# --- apply recipe ---
cp "$RECIPE_YML_PATH" "$PROJECT_ROOT/rewrite.yml"
phase="recipe"
t0=$(date +%s)
PLUGIN=org.openrewrite.maven:rewrite-maven-plugin:6.12.0
COORDS=org.openrewrite.recipe:rewrite-migrate-java:3.12.0,org.openrewrite.recipe:rewrite-spring:6.9.0,org.openrewrite.recipe:rewrite-testing-frameworks:3.11.0,org.openrewrite.recipe:rewrite-hibernate:2.9.0
if [ "$BUILD_TOOL" = "maven" ]; then
  mvn -B -ntp -U $MVN_OPTS_COMPAT "$PLUGIN:run" \
      -Drewrite.activeRecipes="$RECIPE_NAME" \
      -Drewrite.configLocation="$PROJECT_ROOT/rewrite.yml" \
      -Drewrite.recipeArtifactCoordinates="$COORDS" \
      -Drewrite.exportDatatables=true \
      -Drewrite.failOnInvalidActiveRecipes=true \
      >>"$LOG" 2>&1
  recipe_rc=$?
else
  log "gradle path not supported in this rebuild; mark as no-op"
  recipe_rc=0
fi
recipe_elapsed=$(( $(date +%s) - t0 ))
log "recipe rc=$recipe_rc elapsed=${recipe_elapsed}s"

# Per-recipe data table (file -> recipe -> change). Plugin writes one
# CSV per repo module under target/rewrite/datatables/<id>.csv where
# id ends with "RecipesThatMadeChanges" or "SourcesFileResults".
phase="datatables"
{
  echo "module,csv_path,recipe,file"
  find . -path '*/target/rewrite/datatables/*.csv' 2>/dev/null | while read -r f; do
    module=$(echo "$f" | sed 's|/target/rewrite/datatables/.*||; s|^./||')
    # SourcesFileResults columns: sourcePath, recipeName, ... (header tells us)
    if echo "$f" | grep -q SourcesFileResults; then
      tail -n +2 "$f" | awk -F',' -v m="$module" -v p="$f" '{print m","p","$2","$1}'
    fi
  done
} > "$OUT_DIR/per_recipe.csv" 2>>"$LOG" || true
log "per-recipe rows: $(( $(wc -l < "$OUT_DIR/per_recipe.csv") - 1 ))"

# recipe_applied = anything changed in the source tree
diff_files=$(git status --porcelain | wc -l | tr -d ' ')
[ "$diff_files" -gt 0 ] && recipe_applied=1

# --- post-recipe build on JDK 21 ---
export JAVA_HOME="/opt/jdk/21"
export PATH="$JAVA_HOME/bin:$PATH"

phase="post-build"
t0=$(date +%s)
if [ "$BUILD_TOOL" = "maven" ]; then
  if mvn -B -q -DskipTests -ntp $MVN_OPTS_COMPAT -Dmaven.compiler.release=21 -Djava.version=21 package >>"$LOG" 2>&1; then build_post=1; fi
fi
build_elapsed=$(( $(date +%s) - t0 ))
log "build_post=$build_post elapsed=${build_elapsed}s"
[ "$build_post" -eq 1 ] || { failure="${failure:-build-post}"; exit 0; }

# --- post-recipe tests on JDK 21 ---
phase="post-test"
t0=$(date +%s)
if [ "$BUILD_TOOL" = "maven" ]; then
  mvn -B -ntp $MVN_OPTS_COMPAT -Dmaven.compiler.release=21 -Djava.version=21 \
      -Dsurefire.failIfNoSpecifiedTests=false \
      test >>"$LOG" 2>&1 || true
  read -r passed total < <(grep -E '^\[INFO\] Tests run:' "$LOG" | tail -1 | \
    awk '{ for (i=1;i<=NF;i++) { if ($i=="Tests" && $(i+1)=="run:") run=$(i+2)+0;
                                  if ($i=="Failures:") fl=$(i+1)+0;
                                  if ($i=="Errors:") er=$(i+1)+0;
                                  if ($i=="Skipped:") sk=$(i+1)+0 }
            print (run-fl-er-sk), run }')
  tests_post=${passed:-0}; tests_total_post=${total:-0}
fi
test_elapsed=$(( $(date +%s) - t0 ))
log "tests $tests_post / $tests_total_post elapsed=${test_elapsed}s"

phase="done"

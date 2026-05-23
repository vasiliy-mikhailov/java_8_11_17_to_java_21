#!/usr/bin/env bash
# Host-side orchestrator: one docker run per stage, persistent working tree.
# Inputs (env): REPO_ID, REPO_URL, REPO_SHA, JAVA_VERSION, BUILD_TOOL
#
# Stage entry point depends on source Java version:
#   J8  → stage1 (jdk11) → stage2 (jdk17) → stage3 (jdk21)
#   J11 →                    stage2 (jdk17) → stage3 (jdk21)
#   J17 →                                       stage3 (jdk21)
# Each stage accepts ONE specific Java input level and produces the next.
set -uo pipefail
HERE=/home/vmihaylov/java_8_11_17_to_java_21
RECIPES_DIR="$HERE/attempt_4"
STAGE_SCRIPT="$HERE/attempt_4/run_one_stage.sh"
OUT_DIR="$HERE/attempt_4/results/$REPO_ID"
mkdir -p "$OUT_DIR"
LOG="$OUT_DIR/run.log"
: > "$LOG"

WORK_HOST=$(mktemp -d /tmp/iter4-XXXXXX)
chmod 0777 "$WORK_HOST"
trap 'rm -rf "$WORK_HOST"' EXIT

case "$JAVA_VERSION" in
  8)  STAGES=("11:stage1" "17:stage2" "21:stage3") ;;
  11) STAGES=("17:stage2" "21:stage3") ;;
  17) STAGES=("21:stage3") ;;
  *)  STAGES=("21:stage3") ;;
esac

run_stage() {
  local jdk="$1" phase="$2" recipe_arg="$3"
  local cname="iter4-${REPO_ID//\//_}-${jdk}-${phase}-$$"
  docker run --rm --name "$cname" \
    -e STAGE_JDK="$jdk" \
    -e STAGE_RECIPE="$recipe_arg" \
    -e STAGE_LOG="/out/$(basename "$LOG")" \
    -e BUILD_TOOL="$BUILD_TOOL" \
    -e PHASE="$phase" \
    -v "$WORK_HOST:/work" \
    -v "$STAGE_SCRIPT:/opt/scripts/run_one_stage.sh:ro" \
    -v "$RECIPES_DIR/stage1/_recipe/rewrite.yml:/recipes/stage1.yml:ro" \
    -v "$RECIPES_DIR/stage2/_recipe/rewrite.yml:/recipes/stage2.yml:ro" \
    -v "$RECIPES_DIR/stage3/_recipe/rewrite.yml:/recipes/stage3.yml:ro" \
    -v "$OUT_DIR:/out" \
    -v "$HOME/.m2-fitness:/root/.m2" \
    --memory 4g --cpus 2.0 \
    --entrypoint /opt/scripts/run_one_stage.sh \
    j21-fitness:latest >> "$LOG" 2>&1
  return $?
}

echo "[$(date +%H:%M:%S)] clone $REPO_URL @ $REPO_SHA" >> "$LOG"
git clone --filter=blob:none --no-checkout "$REPO_URL" "$WORK_HOST/src" >> "$LOG" 2>&1 || { echo "{\"repo_id\":\"$REPO_ID\",\"failure\":\"clone\"}" > "$OUT_DIR/metrics.json"; exit 1; }
( cd "$WORK_HOST/src" && git fetch --depth 50 origin "$REPO_SHA" >> "$LOG" 2>&1 || true; git checkout --detach "$REPO_SHA" >> "$LOG" 2>&1 ) || { echo "{\"repo_id\":\"$REPO_ID\",\"failure\":\"checkout\"}" > "$OUT_DIR/metrics.json"; exit 1; }

declare -a stage_jdks=() stage_rcs=() stage_elapsed=()
build_pre=0
build_post=0

echo "[$(date +%H:%M:%S)] baseline build_pre under JDK $JAVA_VERSION" >> "$LOG"
t0=$(date +%s)
if run_stage "$JAVA_VERSION" build_pre ""; then build_pre=1; fi
echo "  build_pre=$build_pre (elapsed=$(( $(date +%s) - t0 ))s)" >> "$LOG"

for stage_spec in "${STAGES[@]}"; do
  jdk="${stage_spec%%:*}"
  stage_name="${stage_spec#*:}"
  recipe_path="/recipes/${stage_name}.yml"
  echo "[$(date +%H:%M:%S)] === $stage_name (jdk $jdk) ===" >> "$LOG"
  t0=$(date +%s)
  run_stage "$jdk" recipe "$recipe_path"
  rc=$?
  elapsed=$(( $(date +%s) - t0 ))
  stage_jdks+=("$jdk")
  stage_rcs+=("$rc")
  stage_elapsed+=("$elapsed")
  echo "  $stage_name rc=$rc elapsed=${elapsed}s" >> "$LOG"
done

echo "[$(date +%H:%M:%S)] final build under JDK 21" >> "$LOG"
t0=$(date +%s)
if run_stage 21 build_post ""; then build_post=1; fi
echo "  build_post=$build_post (elapsed=$(( $(date +%s) - t0 ))s)" >> "$LOG"

( cd "$WORK_HOST/src" && git diff > "$OUT_DIR/diff.patch" 2>/dev/null ) || true

stages_json="["
for i in "${!stage_jdks[@]}"; do
  [ $i -gt 0 ] && stages_json+=","
  stages_json+="{\"jdk\":${stage_jdks[$i]},\"rc\":${stage_rcs[$i]},\"elapsed_s\":${stage_elapsed[$i]}}"
done
stages_json+="]"
cat > "$OUT_DIR/metrics.json" <<JSON
{
  "repo_id": "$REPO_ID",
  "repo_url": "$REPO_URL",
  "sha": "$REPO_SHA",
  "java_version": $JAVA_VERSION,
  "build_tool": "$BUILD_TOOL",
  "build_pre": $build_pre,
  "build_post": $build_post,
  "stages": $stages_json
}
JSON

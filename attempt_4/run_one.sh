#!/usr/bin/env bash
# Host-side wrapper: launches j21-fitness with the attempt_4 staged entrypoint.
# Stage list is computed from REPO's declared JAVA_VERSION:
#   J8  -> stage1(jdk11), stage2(jdk17), stage3(jdk21)
#   J11 -> stage2(jdk17), stage3(jdk21)
#   J17 -> stage3(jdk21) only
set -uo pipefail
HERE=/home/vmihaylov/java_8_11_17_to_java_21
RECIPES_DIR="$HERE/attempt_4"
RUNNER="$HERE/attempt_4/run_one_repo_staged.sh"
OUT_DIR="$HERE/attempt_4/results/$REPO_ID"
mkdir -p "$OUT_DIR"

case "$JAVA_VERSION" in
  8)  STAGES="11:/recipes/stage1.yml,17:/recipes/stage2.yml,21:/recipes/stage3.yml" ;;
  11) STAGES="17:/recipes/stage2.yml,21:/recipes/stage3.yml" ;;
  17) STAGES="21:/recipes/stage3.yml" ;;
  *)  STAGES="21:/recipes/stage3.yml" ;;
esac

CONTAINER_NAME="iter4-${REPO_ID//\//_}-$$"
docker run --rm --name "$CONTAINER_NAME" \
  -e REPO_URL="$REPO_URL" \
  -e REPO_SHA="$REPO_SHA" \
  -e REPO_ID="$REPO_ID" \
  -e JAVA_VERSION="$JAVA_VERSION" \
  -e BUILD_TOOL="$BUILD_TOOL" \
  -e STAGES="$STAGES" \
  -e OUT_DIR=/out \
  -v "$RUNNER:/opt/scripts/run_one_repo_staged.sh:ro" \
  -v "$RECIPES_DIR/stage1/_recipe/rewrite.yml:/recipes/stage1.yml:ro" \
  -v "$RECIPES_DIR/stage2/_recipe/rewrite.yml:/recipes/stage2.yml:ro" \
  -v "$RECIPES_DIR/stage3/_recipe/rewrite.yml:/recipes/stage3.yml:ro" \
  -v "$OUT_DIR:/out" \
  -v "$HOME/.m2-fitness:/root/.m2" \
  --memory 4g --cpus 2.0 \
  --entrypoint /opt/scripts/run_one_repo_staged.sh \
  j21-fitness:latest 2>&1 | tail -3

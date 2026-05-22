#!/usr/bin/env bash
# Per-repo runner for attempt_2 iter-0.
# Inputs (env): REPO_ID, REPO_URL, REPO_SHA, JAVA_VERSION, BUILD_TOOL
# Outputs to attempt_2/iter-006/results/<REPO_ID>/{metrics.json, diff.patch, run.log, per_recipe.csv}
set -uo pipefail
HERE=/home/vmihaylov/java_8_11_17_to_java_21
RECIPE_YML="$HERE/attempt_2/iter-006/_recipe/rewrite.yml"
OUT_DIR="$HERE/attempt_2/iter-006/results/$REPO_ID"
mkdir -p "$OUT_DIR"
docker run --rm \
  -e REPO_URL="$REPO_URL" \
  -e REPO_SHA="$REPO_SHA" \
  -e REPO_ID="$REPO_ID" \
  -e JAVA_VERSION="$JAVA_VERSION" \
  -e BUILD_TOOL="$BUILD_TOOL" \
  -e RECIPE_NAME=com.fitness.iter6.MigrateToJava21 \
  -e RECIPE_YML_PATH=/recipe/rewrite.yml \
  -e OUT_DIR=/out \
  -v "$RECIPE_YML:/recipe/rewrite.yml:ro" \
  -v "$OUT_DIR:/out" \
  -v "$HOME/.m2-fitness:/root/.m2" \
  --memory 4g --cpus 2.0 \
  j21-fitness:latest 2>&1 | tail -3

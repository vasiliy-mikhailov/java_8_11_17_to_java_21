#!/usr/bin/env bash
# Run the real ralph loop against the full 34-repo dataset on YOUR machine.
#
# What this does, end to end:
#   1. Sanity-check Docker is up.
#   2. Build the multi-JDK runner image (j21-fitness:latest).
#   3. Run the orchestrator's ralph loop:
#        - For each candidate, fan out one container per dataset repo,
#          each running mvn rewrite:run + javac --release 21,
#          emitting metrics.json.
#        - Aggregate to a corpus score (weighted composite, mean of cell-means).
#        - Hill-climb (mutator), plateau-detect, multi-start.
#   4. Write results/best.json with the winning recipe + iteration trace.
#
# Why a script instead of the README make targets: this is a self-contained
# end-to-end runner that captures every step + sane logging, so you don't
# have to glue Make targets in sequence.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

# Configurable
IMAGE="${IMAGE:-j21-fitness:latest}"
DATASET="${DATASET:-$(realpath java21-migration-dataset.json)}"
POOL="${POOL:-recipes/pool.yml}"
SEED="${SEED:-recipes/seed.yml}"
RESULTS="${RESULTS:-results}"
PARALLEL="${PARALLEL:-6}"
MAX_ITER="${MAX_ITER:-20}"
PROPOSALS="${PROPOSALS:-6}"
RESTARTS="${RESTARTS:-3}"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" ; }

log "preflight"
command -v docker >/dev/null || { echo "ERROR: docker not in PATH" >&2; exit 1; }
docker info >/dev/null 2>&1 || { echo "ERROR: docker daemon not reachable" >&2; exit 1; }
python3 -c "import yaml" 2>/dev/null || { echo "ERROR: please 'pip install pyyaml'" >&2; exit 1; }
[ -f "$DATASET" ] || { echo "ERROR: dataset not found at $DATASET" >&2; exit 1; }
[ -f "$POOL" ]    || { echo "ERROR: pool not found at $POOL" >&2; exit 1; }
[ -f "$SEED" ]    || { echo "ERROR: seed not found at $SEED" >&2; exit 1; }

log "building runner image (one time, ~3-5 min)"
docker build -t "$IMAGE" .

log "smoke-test image"
docker run --rm "$IMAGE" /opt/scripts/run_one_repo.sh </dev/null 2>&1 | head -1 || true

# Multi-start: run the ralph loop $RESTARTS times with different RNG seeds,
# keep the best run. The orchestrator already handles per-iteration state;
# we just wrap it.
best_score=0
best_dir=""
for r in $(seq 1 "$RESTARTS"); do
  rng_seed=$((42 * r * r))
  run_dir="$RESULTS/restart-$r"
  mkdir -p "$run_dir"
  log "ralph loop restart $r/$RESTARTS  (rng_seed=$rng_seed, results in $run_dir)"
  python3 -m orchestrator.orchestrator \
    --dataset   "$DATASET" \
    --pool      "$POOL" \
    --seed      "$SEED" \
    --results   "$run_dir" \
    --parallel  "$PARALLEL" \
    --max-iter  "$MAX_ITER" \
    --proposals "$PROPOSALS" \
    --plateau-eps 0.01 \
    --plateau-window 3 \
    --rng-seed  "$rng_seed" \
    2>&1 | tee "$run_dir/loop.log"

  this_score=$(jq -r '.best_score' "$run_dir/best.json")
  log "restart $r finished with score=$this_score"
  if awk "BEGIN{exit !($this_score > $best_score)}"; then
    best_score=$this_score
    best_dir=$run_dir
  fi
done

log "winning restart: $best_dir  (score=$best_score)"
cp "$best_dir/best.json" "$RESULTS/best.json"
jq '{best_score, iterations_run, best: (.best | join("\n  - "))}' "$RESULTS/best.json"

log "done. champion rewrite.yml:"
python3 - <<'PY'
import json
b = json.load(open("results/best.json"))
print("type: specs.openrewrite.org/v1beta/recipe")
print("name: com.fitness.champion.MigrateToJava21")
print(f"displayName: Champion of full-dataset ralph loop (score={b['best_score']:.4f})")
print("recipeList:")
for r in b["best"]:
    print(f"  - {r}")
PY

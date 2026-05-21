"""Drive the real HillClimber against the reasoned fitness oracle.

This is "Claude in the ralph loop" — the mutator searches, the oracle
scores, and we capture a full iteration trace plus the winning recipe.

The mutator code is unchanged from the production harness; only the
fitness function is the reasoned simulator instead of the Docker runner.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator.mutator import HillClimber, MutatorConfig, load_pool, load_seed, render_rewrite_yml
from orchestrator.reasoned_fitness import make_fitness


HERE = Path(__file__).parent
DATASET = HERE / "java21-migration-dataset.json"
POOL = HERE / "recipes" / "pool.yml"
SEED = HERE / "recipes" / "seed-weak.yml"
OUT_DIR = HERE / "ralph-run"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    pool = load_pool(POOL)
    seed = load_seed(SEED)
    fitness = make_fitness(POOL, DATASET)

    # Multi-start hill climbing: 5 RNG seeds, keep the best run.
    # Real ralph loops do this implicitly when restarted with a perturbed
    # candidate; we make it explicit so the report is reproducible.
    rng_seeds = [42, 137, 1337, 2718, 31415]
    runs = []
    for s in rng_seeds:
        cfg = MutatorConfig(
            proposals_per_iter=8,
            plateau_eps=0.005,
            plateau_window=5,
            max_iter=20,
            max_recipes=14,
            min_recipes=3,
            seed=s,
            gap_bias_p=0.85,
        )
        climber = HillClimber(pool, seed, fitness=fitness, cfg=cfg)
        runs.append((s, climber.run()))
    runs.sort(key=lambda x: x[1]["best_score"], reverse=True)
    best_seed, result = runs[0]
    print(f"Best of {len(rng_seeds)} restarts: seed={best_seed} "
          f"score={result['best_score']:.4f}")
    print("All runs:", [(s, round(r['best_score'], 4)) for s, r in runs])

    # Pretty per-iteration trace
    trace_lines = []
    seed_score = result["history"][0]["score"]
    trace_lines.append(f"seed   score={seed_score:.4f}  recipes={len(seed.recipes)}")
    cur_score = seed_score
    cur_recipes = list(seed.recipes)
    for h in result["history"][1:]:
        iter_n = h["iter"]
        considered = h["considered"]
        top = considered[0]
        improved = h["improved"]
        marker = "+" if improved else " "
        if improved:
            cur_score = top["score"]
            cur_recipes = top["recipes"]
        line = (f"iter {iter_n:>2}{marker}  best={cur_score:.4f}  "
                f"top-proposal={top['score']:.4f}  "
                f"n={len(top['recipes'])}  "
                f"considered={[round(c['score'], 3) for c in considered]}")
        trace_lines.append(line)
    trace = "\n".join(trace_lines)

    # Write artifacts
    (OUT_DIR / "iteration-trace.txt").write_text(trace + "\n")
    (OUT_DIR / "iteration-trace.json").write_text(json.dumps(result, indent=2))
    (OUT_DIR / "best-rewrite.yml").write_text(
        render_rewrite_yml(
            type("C", (), {"recipes": result["best"]})(),
            "com.fitness.champion.MigrateToJava21"
        )
    )

    # Per-cell breakdown of the winning candidate
    final_fit = fitness(type("C", (), {"recipes": result["best"]})())
    per_cell_lines = []
    for (j, fam), s in sorted(final_fit.per_cell.items()):
        per_cell_lines.append(f"  java{j:>2} / {fam:<26}  {s:.4f}")
    (OUT_DIR / "best-per-cell.txt").write_text("\n".join(per_cell_lines) + "\n")

    print("=" * 70)
    print(trace)
    print("=" * 70)
    print(f"\nWinning recipe set ({len(result['best'])} recipes), score {result['best_score']:.4f}:")
    for r in result["best"]:
        print(f"  - {r}")
    print(f"\nPer-cell scores on winner:")
    print("\n".join(per_cell_lines))
    print(f"\nArtifacts written to {OUT_DIR}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

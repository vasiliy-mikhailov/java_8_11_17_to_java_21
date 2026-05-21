"""End-to-end ralph loop. Glues mutator + Docker repo_runner + scorer.

Run:
    python -m orchestrator.orchestrator \\
        --dataset ../java21-migration-dataset.json \\
        --pool ../recipes/pool.yml \\
        --seed ../recipes/seed.yml \\
        --results ../results \\
        --parallel 4
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from .mutator import (
    Candidate,
    HillClimber,
    MutatorConfig,
    load_pool,
    load_seed,
    render_rewrite_yml,
)
from .repo_runner import RunRequest, evaluate_candidate
from .scorer import load_and_score, pretty


log = logging.getLogger("orchestrator")
RECIPE_NAME = "com.fitness.candidate.MigrateToJava21"


def dataset_to_requests(dataset_path: Path) -> list[RunRequest]:
    data = json.loads(dataset_path.read_text())
    reqs = []
    for entry in data["repos"]:
        if not entry.get("url") or not entry.get("commit_sha"):
            continue  # skip GAP rows
        sha = entry["commit_sha"].strip()
        # The dataset stores some entries as "tag <name>" or "<short>";
        # leave that to the runner script (git checkout handles both).
        reqs.append(RunRequest(
            repo_id=entry["id"],
            url=entry["url"] + ".git",
            sha=sha if " " not in sha else sha.split()[-1],
            java_version=entry["java_version"],
            build_tool=entry["build_tool"],
        ))
    return reqs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--pool", type=Path, required=True)
    parser.add_argument("--seed", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--max-iter", type=int, default=20)
    parser.add_argument("--proposals", type=int, default=5)
    parser.add_argument("--plateau-eps", type=float, default=0.02)
    parser.add_argument("--plateau-window", type=int, default=3)
    parser.add_argument("--rng-seed", type=int, default=0xC0FFEE,
                        help="RNG seed for the mutator; differing seeds enable multi-start.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip Docker; use a synthetic fitness function "
                             "(useful for unit testing the loop).")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    pool = load_pool(args.pool)
    seed = load_seed(args.seed)
    requests = dataset_to_requests(args.dataset)
    log.info("loaded pool=%d recipes, seed=%d active, dataset=%d repos",
             len(pool), len(seed.recipes), len(requests))

    args.results.mkdir(parents=True, exist_ok=True)

    iter_counter = {"n": 0}

    def fitness(cand: Candidate):
        iter_counter["n"] += 1
        label = f"iter-{iter_counter['n']:03d}"
        rewrite_yml = render_rewrite_yml(cand, RECIPE_NAME)
        log.info("evaluating %s with %d recipes", label, len(cand.recipes))

        if args.dry_run:
            # Synthetic fitness: prefers compositions that contain
            # UpgradeToJava21 + JavaxMigrationToJakarta + JUnit4to5
            # and penalises huge ones. Useful for shaking out the loop.
            wanted = {
                "org.openrewrite.java.migrate.UpgradeToJava21": 0.30,
                "org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta": 0.20,
                "org.openrewrite.java.testing.junit5.JUnit4to5Migration": 0.15,
                "org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_3": 0.10,
                "org.openrewrite.hibernate.MigrateToHibernate62": 0.05,
            }
            base = sum(w for r, w in wanted.items() if r in cand.recipes)
            penalty = max(0, len(cand.recipes) - 8) * 0.02
            score = max(0.0, min(1.0, base - penalty + 0.20))  # +0.20 noise floor
            class _Fake:
                pass
            f = _Fake()
            f.score = score
            f.per_cell = {(8, "spring-boot-2"): score, (17, "junit4-mockito"): score}
            f.gap_cells = lambda: []
            return f

        iter_dir = evaluate_candidate(
            requests=requests,
            recipe_yml_text=rewrite_yml,
            recipe_name=RECIPE_NAME,
            results_root=args.results,
            parallel=args.parallel,
            iter_label=label,
        )
        dataset_rows = json.loads(args.dataset.read_text())["repos"]
        corpus = load_and_score(iter_dir, dataset_rows)
        log.info("%s -> %.4f", label, corpus.score)
        # Persist the score next to the iteration outputs.
        (iter_dir / "corpus_score.json").write_text(
            json.dumps(
                {
                    "score": corpus.score,
                    "per_cell": {f"{j}:{f}": s for (j, f), s in corpus.per_cell.items()},
                    "recipes": list(cand.recipes),
                },
                indent=2,
            )
        )
        return corpus

    cfg = MutatorConfig(
        proposals_per_iter=args.proposals,
        plateau_eps=args.plateau_eps,
        plateau_window=args.plateau_window,
        max_iter=args.max_iter,
        seed=args.rng_seed,
    )
    climber = HillClimber(pool=pool, seed_candidate=seed, fitness=fitness, cfg=cfg)
    result = climber.run()

    out = args.results / "best.json"
    out.write_text(json.dumps(result, indent=2))
    log.info("ralph loop done. best score=%.4f, %d iterations",
             result["best_score"], result["iterations_run"])
    log.info("best recipe list:")
    for r in result["best"]:
        log.info("  - %s", r)
    log.info("written: %s", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

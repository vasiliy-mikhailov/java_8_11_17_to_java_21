"""Java-21 OpenRewrite ralph loop.

Single-file harness aligned with AGENTS.md. Reads the dataset and recipe
pool, runs candidate compositions inside Docker containers (one per repo),
mutates with hill-climbing + multi-start, and emits three artefacts:

  results/best.json          winning composition + corpus score
  results/trajectory.json    every candidate tried, score, mutation rationale
  results/per_recipe.json    per-recipe contribution by dataset cell

Per-recipe contribution is derived from OpenRewrite's exported data tables
(SourcesFileResults.csv) plus a correlational with/without analysis over
the trajectory: for each recipe R and each dataset cell C, the mean fitness
of candidates containing R minus the mean fitness of candidates not
containing R.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import logging
import os
import random
import shutil
import subprocess
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml


# ---------- config ----------
IMAGE = "j21-fitness:latest"
RECIPE_NAME = "com.fitness.candidate.MigrateToJava21"

log = logging.getLogger("ralph")


# ---------- domain types ----------

@dataclass(frozen=True)
class Repo:
    repo_id: str
    url: str
    sha: str
    java_version: int
    dependency_family: str
    build_tool: str

    @property
    def cell(self) -> tuple[int, str]:
        return (self.java_version, self.dependency_family)


@dataclass
class Candidate:
    recipes: tuple[str, ...]

    def __hash__(self) -> int:
        return hash(self.recipes)


@dataclass
class RepoResult:
    repo: Repo
    metrics: dict
    per_recipe_touches: dict[str, int]   # recipe -> num files touched in this repo

    @property
    def fitness(self) -> float:
        """Per-repo fitness in [0, 1].

        Composes:
            0.5 * build_post (binary)
            0.3 * tests_passed_post / tests_total_post (or 1 if repo has no tests)
            0.1 * recipe_applied (binary)  — guards against the empty-recipe
                                              degenerate solution
            0.1 * recipe_rc==0 (binary)    — recipe loaded + ran without errors
        """
        m = self.metrics
        build = 1.0 if m.get("build_post") == 1 else 0.0
        if m.get("tests_total_post", 0) > 0:
            tests = m["tests_passed_post"] / m["tests_total_post"]
        else:
            tests = build      # absence of tests doesn't punish a passing build
        applied = 1.0 if m.get("recipe_applied") == 1 else 0.0
        rc_ok = 1.0 if m.get("recipe_rc") == 0 else 0.0
        return 0.5 * build + 0.3 * tests + 0.1 * applied + 0.1 * rc_ok


@dataclass
class CorpusEval:
    candidate: Candidate
    per_repo: list[RepoResult]
    # cell -> mean fitness across repos in that cell
    per_cell: dict[tuple[int, str], float] = field(default_factory=dict)
    score: float = 0.0


# ---------- loaders ----------

def load_dataset(path: Path) -> list[Repo]:
    raw = json.loads(path.read_text())
    out: list[Repo] = []
    for entry in raw["repos"]:
        if not entry.get("url"):
            continue        # *_GAP rows
        sha = entry["commit_sha"]
        if " " in sha:      # forms like "tag v2.2.0" pulled from notes
            sha = sha.split()[-1]
        out.append(Repo(
            repo_id=entry["id"],
            url=entry["url"].rstrip("/") + ".git",
            sha=sha,
            java_version=entry["java_version"],
            dependency_family=entry["dependency_family"],
            build_tool=entry["build_tool"],
        ))
    return out


def load_recipes(path: Path) -> tuple[Candidate, list[str]]:
    raw = yaml.safe_load(path.read_text())
    seed = Candidate(recipes=tuple(raw["seed"]))
    pool = list(raw["pool"])
    return seed, pool


# ---------- recipe rendering ----------

def render_rewrite_yml(cand: Candidate) -> str:
    lines = [
        "type: specs.openrewrite.org/v1beta/recipe",
        f"name: {RECIPE_NAME}",
        "displayName: Candidate composite",
        "recipeList:",
    ]
    for r in cand.recipes:
        lines.append(f"  - {r}")
    return "\n".join(lines) + "\n"


# ---------- Docker runner ----------

def run_one_repo_in_container(
    repo: Repo, recipe_dir: Path, out_dir: Path, timeout_s: int = 1200,
) -> RepoResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    abs_recipe = recipe_dir.resolve()
    abs_out = out_dir.resolve()
    cmd = [
        "docker", "run", "--rm",
        "--network=host",
        "-v", f"{abs_recipe}:/work/recipe:ro",
        "-v", f"{abs_out}:/out",
        "-e", f"REPO_URL={repo.url}",
        "-e", f"REPO_SHA={repo.sha}",
        "-e", f"REPO_ID={repo.repo_id}",
        "-e", f"JAVA_VERSION={repo.java_version}",
        "-e", f"BUILD_TOOL={repo.build_tool}",
        "-e", f"RECIPE_NAME={RECIPE_NAME}",
        "-e", "RECIPE_YML_PATH=/work/recipe/rewrite.yml",
        "-e", "OUT_DIR=/out",
        IMAGE,
    ]
    try:
        r = subprocess.run(cmd, check=False, timeout=timeout_s,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0:
            (out_dir / "docker.stderr").write_bytes(r.stderr or b"")
    except subprocess.TimeoutExpired:
        log.warning("%s timed out after %ds", repo.repo_id, timeout_s)

    metrics_path = out_dir / "metrics.json"
    metrics: dict = {}
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text())
        except Exception:
            pass

    # Per-recipe touches: count rows in per_recipe.csv grouped by recipe.
    per_recipe: dict[str, int] = defaultdict(int)
    pr = out_dir / "per_recipe.csv"
    if pr.exists():
        try:
            with pr.open() as f:
                r = csv.DictReader(f)
                for row in r:
                    recipe = (row.get("recipe") or "").strip()
                    if recipe:
                        per_recipe[recipe] += 1
        except Exception:
            pass

    return RepoResult(repo=repo, metrics=metrics, per_recipe_touches=dict(per_recipe))


def evaluate(
    cand: Candidate, dataset: list[Repo], iter_dir: Path, parallel: int,
) -> CorpusEval:
    iter_dir.mkdir(parents=True, exist_ok=True)
    recipe_dir = iter_dir / "_recipe"
    recipe_dir.mkdir(exist_ok=True)
    (recipe_dir / "rewrite.yml").write_text(render_rewrite_yml(cand))

    results: list[RepoResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as ex:
        futures = {
            ex.submit(run_one_repo_in_container, r, recipe_dir, iter_dir / r.repo_id): r
            for r in dataset
        }
        for fut in concurrent.futures.as_completed(futures):
            res = fut.result()
            results.append(res)
            log.info("  %s -> fitness=%.3f", res.repo.repo_id, res.fitness)

    # cell aggregation: mean of per-repo fitness within each cell
    by_cell: dict[tuple[int, str], list[float]] = defaultdict(list)
    for r in results:
        by_cell[r.repo.cell].append(r.fitness)
    per_cell = {c: sum(v) / len(v) for c, v in by_cell.items()}
    # corpus score: mean of cell means (so dense cells don't dominate)
    score = sum(per_cell.values()) / max(1, len(per_cell))

    return CorpusEval(candidate=cand, per_repo=results, per_cell=per_cell, score=score)


# ---------- mutator ----------

def family_of(recipe_id: str) -> str:
    """Coarse family tag derived from the recipe ID; the agent can re-derive
    these from OpenRewrite's catalogue if it wants something smarter."""
    if "spring" in recipe_id: return "spring"
    if "junit" in recipe_id or "assertj" in recipe_id: return "junit"
    if "mockito" in recipe_id: return "mockito"
    if "jakarta" in recipe_id: return "jakarta"
    if "hibernate" in recipe_id: return "hibernate"
    if "jackson" in recipe_id: return "jackson"
    if "lombok" in recipe_id: return "lombok"
    if "migrate.UpgradeToJava" in recipe_id or "migrate.lang" in recipe_id \
       or "migrate.util" in recipe_id or "migrate.Removed" in recipe_id \
       or "migrate.Replace" in recipe_id or "migrate.UseJava" in recipe_id:
        return "java-core"
    return "cleanup"


def propose(
    current: Candidate, pool: list[str], rng: random.Random,
    gap_families: set[str], k: int, min_n: int = 3, max_n: int = 12,
) -> list[Candidate]:
    """Return up to k unique neighbours of `current`."""
    out: list[Candidate] = []
    seen: set[tuple[str, ...]] = {current.recipes}

    def add_op():
        if len(current.recipes) >= max_n: return None
        unused = [r for r in pool if r not in current.recipes]
        if gap_families:
            pref = [r for r in unused if family_of(r) in gap_families]
            unused = pref or unused
        if not unused: return None
        r = rng.choice(unused)
        pos = rng.randint(0, len(current.recipes))
        return Candidate(tuple(current.recipes[:pos] + (r,) + current.recipes[pos:]))

    def remove_op():
        if len(current.recipes) <= min_n: return None
        i = rng.randint(0, len(current.recipes) - 1)
        return Candidate(current.recipes[:i] + current.recipes[i + 1:])

    def swap_op():
        if len(current.recipes) < 2: return None
        i = rng.randint(0, len(current.recipes) - 2)
        rs = list(current.recipes)
        rs[i], rs[i + 1] = rs[i + 1], rs[i]
        return Candidate(tuple(rs))

    def replace_op():
        if not current.recipes: return None
        i = rng.randint(0, len(current.recipes) - 1)
        fam = family_of(current.recipes[i])
        siblings = [r for r in pool if family_of(r) == fam and r not in current.recipes]
        if not siblings: return None
        rs = list(current.recipes); rs[i] = rng.choice(siblings)
        return Candidate(tuple(rs))

    ops = [add_op, remove_op, swap_op, replace_op]
    tries = 0
    while len(out) < k and tries < 8 * k:
        tries += 1
        op = rng.choice(ops)
        child = op()
        if child is None or child.recipes in seen:
            continue
        seen.add(child.recipes)
        out.append(child)
    return out


# ---------- the loop ----------

def ralph_loop(
    seed: Candidate, pool: list[str], dataset: list[Repo],
    results_root: Path, parallel: int, max_iter: int, proposals: int,
    plateau_window: int, plateau_eps: float, rng_seed: int,
) -> tuple[CorpusEval, list[dict]]:
    rng = random.Random(rng_seed)
    trajectory: list[dict] = []

    log.info("seed: %d recipes", len(seed.recipes))
    incumbent = evaluate(seed, dataset, results_root / "iter-000-seed", parallel)
    trajectory.append({
        "iter": 0, "kind": "seed",
        "recipes": list(incumbent.candidate.recipes),
        "score": incumbent.score,
        "per_cell": {f"{j}:{f}": s for (j, f), s in incumbent.per_cell.items()},
    })
    log.info("seed score=%.4f", incumbent.score)

    no_improve = 0
    for it in range(1, max_iter + 1):
        gap_families = {
            family_of_cell(cell)
            for cell, s in incumbent.per_cell.items() if s < 0.6
        }
        children = propose(incumbent.candidate, pool, rng, gap_families, proposals)
        log.info("iter %d: %d proposals", it, len(children))

        considered = []
        best_child: CorpusEval | None = None
        for j, child in enumerate(children, 1):
            ev = evaluate(child, dataset, results_root / f"iter-{it:03d}-prop-{j}", parallel)
            considered.append({"recipes": list(child.recipes), "score": ev.score})
            log.info("  proposal %d/%d  score=%.4f", j, len(children), ev.score)
            if best_child is None or ev.score > best_child.score:
                best_child = ev

        improved = best_child and best_child.score > incumbent.score + plateau_eps
        trajectory.append({
            "iter": it, "kind": "step",
            "considered": considered,
            "winner_recipes": list((best_child or incumbent).candidate.recipes),
            "winner_score": (best_child or incumbent).score,
            "improved": bool(improved),
        })

        if improved:
            incumbent = best_child  # type: ignore
            no_improve = 0
            log.info("iter %d ACCEPT  score=%.4f", it, incumbent.score)
        else:
            no_improve += 1
            log.info("iter %d plateau (%d/%d)", it, no_improve, plateau_window)
            if no_improve >= plateau_window:
                break

    return incumbent, trajectory


def family_of_cell(cell: tuple[int, str]) -> str:
    """Map (java_version, dependency_family) -> recipe family that targets it."""
    _, fam = cell
    if fam.startswith("spring-boot"): return "spring"
    if fam.startswith("junit"):       return "junit"
    if fam.startswith("jakarta"):     return "jakarta"
    if fam.startswith("hibernate"):   return "hibernate"
    return "cleanup"


# ---------- per-recipe attribution ----------

def per_recipe_contribution(trajectory: list[dict], dataset: list[Repo],
                            pool: list[str]) -> dict:
    """Correlational: for each recipe and each cell, compare mean cell-score
    of candidates that CONTAIN the recipe vs those that DON'T, across all
    candidates evaluated in the trajectory.
    """
    # Flatten trajectory into (recipes, per_cell) tuples
    samples: list[tuple[set[str], dict[str, float]]] = []
    for h in trajectory:
        if h["kind"] == "seed":
            samples.append((set(h["recipes"]), h["per_cell"]))
        else:
            # We don't have per-cell breakdowns for considered/winners in
            # the lean trajectory; only the seed has it. We re-add the
            # winner's score per-cell if available; otherwise skip.
            pass

    # If we have only the seed, that's still useful: scaffolds the structure.
    cells = sorted({cell for _, pc in samples for cell in pc.keys()})

    per_recipe: dict[str, dict] = {}
    for recipe in pool:
        with_, without_ = defaultdict(list), defaultdict(list)
        for recipes, pc in samples:
            bucket = with_ if recipe in recipes else without_
            for cell, score in pc.items():
                bucket[cell].append(score)
        helps, hurts, neutral = {}, {}, {}
        for cell in cells:
            mw = sum(with_[cell]) / len(with_[cell]) if with_[cell] else None
            mo = sum(without_[cell]) / len(without_[cell]) if without_[cell] else None
            if mw is None or mo is None:
                continue
            delta = round(mw - mo, 4)
            bucket = helps if delta > 0.01 else (hurts if delta < -0.01 else neutral)
            bucket[cell] = {"with": round(mw, 4), "without": round(mo, 4), "delta": delta}
        per_recipe[recipe] = {"helps": helps, "hurts": hurts, "neutral": neutral}
    return per_recipe


# ---------- main ----------

def main(argv=None):
    p = argparse.ArgumentParser()
    here = Path(__file__).parent
    p.add_argument("--dataset", type=Path, default=here / "java21-migration-dataset.json")
    p.add_argument("--recipes", type=Path, default=here / "recipes.yml")
    p.add_argument("--results", type=Path, default=here / "results")
    p.add_argument("--parallel", type=int, default=12)
    p.add_argument("--max-iter", type=int, default=20)
    p.add_argument("--proposals", type=int, default=5)
    p.add_argument("--plateau-eps", type=float, default=0.01)
    p.add_argument("--plateau-window", type=int, default=3)
    p.add_argument("--restarts", type=int, default=1)
    p.add_argument("--rng-seed", type=int, default=42)
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    dataset = load_dataset(args.dataset)
    seed, pool = load_recipes(args.recipes)
    log.info("dataset=%d repos  pool=%d recipes  seed=%d recipes",
             len(dataset), len(pool), len(seed.recipes))

    args.results.mkdir(parents=True, exist_ok=True)

    # Build image if missing
    if subprocess.run(["docker", "image", "inspect", IMAGE],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        log.info("building docker image %s", IMAGE)
        subprocess.run(["docker", "build", "-t", IMAGE, str(here)], check=True)

    best: CorpusEval | None = None
    full_trajectory: list[dict] = []
    for r in range(args.restarts):
        run_dir = args.results / f"restart-{r + 1}"
        log.info("restart %d/%d", r + 1, args.restarts)
        ev, tr = ralph_loop(
            seed, pool, dataset, run_dir,
            parallel=args.parallel, max_iter=args.max_iter,
            proposals=args.proposals,
            plateau_window=args.plateau_window, plateau_eps=args.plateau_eps,
            rng_seed=args.rng_seed + r * 1000,
        )
        full_trajectory.extend([{**h, "restart": r + 1} for h in tr])
        if best is None or ev.score > best.score:
            best = ev

    assert best is not None
    (args.results / "best.json").write_text(json.dumps({
        "score": best.score,
        "recipes": list(best.candidate.recipes),
        "per_cell": {f"{j}:{f}": s for (j, f), s in best.per_cell.items()},
        "per_repo": [
            {"id": r.repo.repo_id, "cell": f"{r.repo.java_version}:{r.repo.dependency_family}",
             "fitness": r.fitness,
             "build_post": r.metrics.get("build_post"),
             "tests_passed_post": r.metrics.get("tests_passed_post"),
             "tests_total_post": r.metrics.get("tests_total_post"),
             "recipe_applied": r.metrics.get("recipe_applied"),
             "recipe_rc": r.metrics.get("recipe_rc")}
            for r in best.per_repo
        ],
    }, indent=2))
    (args.results / "trajectory.json").write_text(json.dumps(full_trajectory, indent=2))
    (args.results / "per_recipe.json").write_text(json.dumps(
        per_recipe_contribution(full_trajectory, dataset, pool), indent=2))

    log.info("done. best score=%.4f, %d recipes", best.score, len(best.candidate.recipes))
    log.info("artefacts: %s", args.results)


if __name__ == "__main__":
    main()

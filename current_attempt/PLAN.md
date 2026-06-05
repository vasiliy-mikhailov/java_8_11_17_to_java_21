# Attempt 12 — randomized-baseline dataset (anti-overfit)

## Why

Attempts 1–11 evaluated against a **fixed-sha** corpus: each datapoint pinned to one baseline
commit. Any improvement loop (manual iteration, and especially the planned GEPA/EvoSkills
optimizers) can then **overfit** to those exact commits — tune `SKILL.md` and the recipe catalog
to the 412 specific poms rather than to the general "bump a Maven project one LTS" task. It also
made baseline quality a *curation* chore (the junk-baseline drops in a10 and a11).

## What changes

The dataset is now **repo names only** (`dataset-repos.json`, 432 unique repos). Shas are **sampled per
run**:

- `tools/sample_shas.py --seed N [--k K] [--compile-check]` clones each repo, samples `K`
  seeded-random commits, detects `jv_from` from the pom, and emits
  `dataset-shas.json = [{repo, sha, jv_from, jv_to}]` where `jv_to` is the next LTS
  (8→11, 11→17, 17→21).
- A **different `--seed` per attempt/run ⇒ different shas**, so the eval is a moving target.
- Validity is a **runtime filter**, not curation: with `--compile-check`, a sampled commit is
  kept only if it compiles under its `jv_from`; junk (already ≥21, non-compiling) is simply not
  sampled-in. No fixed clean-list to maintain.

## Why this is better

- **Anti-overfitting.** Improvements must generalize across each repo's history, not memorize
  412 commits. GEPA/EvoSkills score against a *distribution* of baselines, not a fixed set.
- **Organic LTS-hop coverage.** The old corpus was 100% 17→21; sampling across history naturally
  surfaces 8→11 and 11→17 baselines (older commits), exercising every bump path.
- **Junk dissolves.** No curated clean corpus; validity is checked at sample time.
- **Bigger effective eval space.** 432 repos × their whole histories ≫ 412 fixed points.

## Carried forward (unchanged baseline artifact)

The `bump-java-version` skill (`.agents/skills/...`), the recipe catalog
(`tech.mikhailov.bump_java_version_recipes`), and the `tools/` harness carry over from attempt 11
(the 95.6%-on-fixed-412 baseline). Attempt 12 changes only **how baselines are drawn**.

## Eval loop (per optimization round)

1. `sample_shas.py --seed=<round> --compile-check` → fresh `dataset-shas.json`.
2. Run the skill (production rung: OpenHands+Qwen) over that dataset; verdict = pom ≥ `jv_to`
   AND baseline-passing tests still pass.
3. Score; keep skill/recipe edits that improve the **mean across seeds** (generalization),
   discard seed-specific gains. (This is where GEPA/EvoSkills plug in later.)

## Open knobs (defaults; tune as we learn)

- `K` shas/repo/run (default 1 → ~432 candidates/run before validity filtering).
- `--compile-check` on for a clean eval set vs off to also test skill robustness to bad baselines.
- Sampling scope: default-branch history (current) vs `--all` branches.
- Seed policy: `seed = attempt/round index` (reproducible per round).

## AGENTS.md (proposed D4 reframe — pending operator approval)

D4 (dataset) changes from "discover + pin compiling baseline shas" to "maintain the **repo list**;
draw baselines per run via the sampler, filtered to compile under `jv_from`." The nearest-
compiling-ancestor logic becomes the sampler's validity filter rather than a one-time curation.

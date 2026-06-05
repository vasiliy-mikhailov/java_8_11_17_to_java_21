# Attempt 12 — randomized-baseline dataset (anti-overfit)

The dataset is **repo names** (`dataset-repos.json`, 432 unique repos). Baselines are **sampled per run**
by `tools/sample_shas.py --seed N [--k K] [--compile-check]`: a different seed yields different
shas, so the eval is a moving target the skill/recipes must generalize to (instead of overfitting
to fixed commits). Sampling across each repo's history also surfaces 8→11 / 11→17 / 17→21 hops
organically, and validity (compiles under `jv_from`) is a runtime filter, not a curation chore.

The `bump-java-version` skill + recipe catalog + `tools/` harness carry forward unchanged from
attempt 11 (the 95.6%-on-fixed-412 baseline). See `PLAN.md`.

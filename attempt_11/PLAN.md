# Attempt 11 — Automate the artifact optimizer (GEPA + EvoSkills)

## Thesis

Attempt 10 climbed 75% → 96.5% (clean corpus) by a single move repeated by hand: see a
failed trajectory → reflect → author a prompt edit or recipe → validate down the rung ladder
→ fold in. That loop works but the human (the operator + Claude) is the bottleneck, and the
hand-written catalog is finite while the residual failures are a long tail of *distinct*
breaking changes. Attempt 11 removes the human from that loop and lets two published
optimizers drive it:

- **GEPA evolves `prompt.md`.** Reflective prompt evolution: mutate the prompt from
  natural-language reflection on rollout traces (the actual `[ERROR]` text + agent reasoning),
  keep a *Pareto front* over per-datapoint scores (no overfitting one repo), ~35× fewer
  rollouts than RL — decisive when one rollout is a multi-minute clone+agent+compile.
- **EvoSkills evolves the recipe catalog.** Synthesize reusable skills/recipes *from failed
  trajectories* via a Skill-Generator ↔ Surrogate-Verifier co-evolution, label-free, verifier
  blind to the generator (no self-confirmation). This automates exactly the ByteBuddy / SB3 /
  WebSecurityConfigurerAdapter rows we wrote by hand.

## Mapping onto this project

| Optimizer concept | This project |
|---|---|
| Genome / candidate | the artifact `(prompt.md, recipe catalog)` |
| Fitness | OH+Qwen-rung success rate on `corpus_clean.json` (432 datapoints) |
| Reflection traces / failed-trajectory corpus | preserved per-repo dialogues in `per_repo_iter/` |
| Multi-fidelity eval | the rung ladder: cheap Claude+Opus screen → expensive OH+Qwen confirm |
| Verifier signal | D3's verdict (`mvn compile` under jv_to + test conservation) |

## Why attempt 10 was the prerequisite, not a detour

GEPA and EvoSkills optimize **against the reward**. A fitness polluted by the ~46
unmigratable junk baselines would have them evolve the artifact to "fix" repos that can never
compile — chasing noise. Attempt 10 delivered the two things these methods require:
1. a **fitness signal that doesn't lie** — `corpus_clean.json` (junk baselines excluded, 15
   baselines recovered to a compiling sha), and
2. a **trace store to reflect on** — whole dialogues preserved per repo across all rungs.

## Starting point

- Seed candidate: `attempt_11/prompt.md` (copied from attempt 10; ≈96.5% on the clean corpus).
- Seed catalog: `tech.mikhailov.bump_java_version_recipes:claude-recipes:1.0.0` (4 Spring recipes) + the bump
  scripts' OpenRewrite cascade.
- Harness: `tools/` (carried from attempt 10 — verdict, ladder, OH driver, digest).

## First deliverables

1. Stand up the GEPA loop over `prompt.md`: candidate → run on a `corpus_clean` minibatch at
   the OH+Qwen rung → reflect on the dialogues of the failures → mutate → Pareto-select.
   Snapshot every candidate to `prompt_snapshots/<sha>.md`.
2. Stand up the EvoSkills loop over the catalog: cluster failed trajectories, synthesize a
   candidate recipe per cluster, co-evolve against the surrogate verifier, snapshot accepted
   recipes to `recipe_snapshots/`.
3. Gate both with the existing strong→weak rung ladder before folding into the live artifact;
   never fold a change that regresses corpus reward.

Target: push the clean-corpus rate from ~96.5% toward the migratable ceiling (~99%) **without
a bigger production model** — the new capability ships as evolved text + recipes inside the
portable artifact, widening the margin over the one-shot OpenRewrite baseline.

## References

- GEPA: Reflective Prompt Evolution Can Outperform Reinforcement Learning — arXiv 2507.19457
  (ICLR 2026 oral); github.com/gepa-ai/gepa
- EvoSkills: Self-Evolving Agent Skills via Co-Evolutionary Verification — arXiv 2604.01687;
  EvoSkill: Automated Skill Discovery for Multi-Agent Systems — arXiv 2603.02766;
  github.com/sentient-agi/EvoSkill

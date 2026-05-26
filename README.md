# java_8_11_17_to_java_21

Automate the universal slice of migrating Java/Maven projects from Java 8 / 11 / 17 to Java 21, so humans only spend time on the per-project residual.

## Approach

The project is driven by a small set of fitness functions defined in `AGENTS.md`. The primary fitness (item 1, the recipe) is a per-repo iterative search:

1. Start from a default sequenced chain (`{label, jdk, recipes}` steps that progressively bump JDK, plugins, and the build).
2. Run it under the matching JDK with `mvn compile` verification after every step.
3. On failure, extract the real `[ERROR]` block from the maven log, feed it to a Qwen-based proposer along with the prior-attempt history, take its mutated chain, retry.
4. The corpus is processed as a multi-pass round-robin — every pass gives every still-FAILing repo K=5 more attempts (continuing its trajectory from the previous pass), then moves on. Iterate passes until one yields zero new PASSes.

Each per-repo trajectory persists to `attempt_7/per_repo_iter/<slug>/trajectory.json`, so the search resumes from cached state across runs and across proposer changes.

The baseline every repo is measured against is the one-shot `org.openrewrite.java.migrate.UpgradeToJava<jv_to>` recipe — i.e. what an unsuspecting maintainer would do.

## Results so far

PASS rate trajectory across attempts (each attempt's champion against the corpus available at the time):

| attempt | champion | corpus | PASS | Δ vs same-attempt iter-0 baseline |
|---|---|---|---|---|
| 1 | rich seed (`UpgradeJavaVersion + JakartaEE10 + UpgradeSpringFramework_6_1 + UpgradeSpringBoot_3_3 + MigrateToHibernate62 + JUnit4to5Migration + MockitoBestPractices + UpgradeToJava21 + RemoveUnusedImports`) | 4-repo smoke | 25 % (1/4 build_post; Qwen quality 4.0/5) | first attempt |
| 3 | (dataset rediscovery, no recipe iteration) | 271 repos | 56 % baseline | — |
| 4 | staged-per-JDK (`UpgradeToJava<N>` + SB3 + Hibernate + Jakarta at each stage) | 271 repos | 68 % | +12 pp |
| 6 | per-target `recipe.yaml` with `if_pom_contains` framework gating | ~494 stages | 71 % | +3 pp over iter-0 |
| 7 | per-repo iterative search over a sequenced default chain (`lombok_bump → java8→11 → plugins17 → build17 → java17_transforms → plugins21 → build21 → java21_transforms`) + Qwen-proposed per-repo mutations | 395 J21-target stages | 78 %+ (in flight) | +13 pp on processed subset |

Numbers track item 1's reward against the one-shot baseline on the same corpus. Caveat: corpus composition changed across attempts, so absolute PASS rate is comparable within an attempt's column but not across rows.

## Current winner recipe

The default sequenced chain used by attempt 7's iterator (per (jv_from, jv_to=21) target):

```
lombok_safe_bump               run under JDK jv_from
  - UpgradeDependencyVersion(org.projectlombok:lombok = 1.18.30)
  - ChangePropertyValue for { lombok.version, org.projectlombok.lombok.version,
    lombok-version, lombokVersion, version.lombok } = 1.18.30
java8_to_java11                run under JDK 11           # only when jv_from = 8
  - org.openrewrite.java.migrate.Java8toJava11
upgrade_plugins_for_java17     run under JDK 11           # when jv_from <= 11
  - org.openrewrite.java.migrate.UpgradePluginsForJava17
upgrade_build_to_java17        run under JDK 17
  - org.openrewrite.java.migrate.UpgradeBuildToJava17
java17_transforms              run under JDK 17           # 16 source transforms
  - InstanceOfPatternMatch, AddSerialAnnotationToSerialVersionUID,
    RemovedRuntimeTraceMethods, RemovedToolProviderConstructor, ...
upgrade_plugins_for_java21     run under JDK 17
  - org.openrewrite.java.migrate.UpgradePluginsForJava21
upgrade_build_to_java21        run under JDK 21
  - org.openrewrite.java.migrate.UpgradeBuildToJava21
java21_transforms              run under JDK 21           # 8 source transforms
  - RemoveIllegalSemicolons, ThreadStopUnsupported, URLConstructorToURICreate,
    SequencedCollection, UseLocaleOf, ReplaceDeprecatedRuntimeExecMethods,
    DeleteDeprecatedFinalize, RemovedSubjectMethods
```

The exact recipe lists and JDK assignments live in `attempt_7/tools/run_sequenced_java.py::plan_for()`.

When this default chain fails on a repo, the per-repo iterator (`attempt_7/tools/iterate_repo.py`) asks Qwen for a mutated chain given the captured failure signal and prior attempts. Qwen's primitive set includes the full attempt-1-champion vocabulary (Jakarta, SB 3.x, Hibernate 6.x, JUnit 4→5, Mockito) plus parameterised `UpgradeDependencyVersion` / `ChangePropertyValue` / `ChangeParentPom` etc. for surgical pom edits.

The corpus is processed by `attempt_7/tools/round_robin.py --K 5 --workers 6`, which drives the iterator multi-pass until one pass produces zero new PASSes.

## Repo layout

```
AGENTS.md                       fitness function contracts (read this first)
attempt_1/                      iter-0..7 trajectory + RESULTS.md
attempt_2/                      dataset rediscovery
attempt_3/                      dataset scale-up to 271 baselines
attempt_4/                      staged-migration baseline + REPORT.md
attempt_5/                      lineage dataset v4
attempt_6/                      ff #1 + #4 composer + executor, iter-0..2 results
attempt_7/                      current — sequenced runner + per-repo iterator
  COMPAT_MATRIX.md              SB <-> JDK <-> Hibernate compatibility table
  corpus_full_sample.json       395 J21-target stages (noise-filtered)
  per_repo_iter/<slug>/         trajectory.json per repo
  sequenced_java/<slug>.json    default-chain A/B results
  tools/
    run_sequenced_java.py       sequenced-chain executor + plan_for()
    iterate_repo.py             per-repo iterator + Qwen proposer
    round_robin.py              multi-pass corpus scheduler
    qwen_synth.py               (legacy) per-stage Qwen synthesizer
```

## Infrastructure

- Maven artifact resolution goes through a local Nexus proxy with Google mirror upstream (fitness 3).
- All recipe execution runs in a `j21-fitness:latest` Docker image with JDK 8/11/17/21 side-by-side (fitness 4).
- Qwen 3.6 27B FP8 served via vLLM at `inference.mikhailov.tech` (fitness 5); consumers default to thinking mode.
- The verifier host stays in a healthy CPU band via worker-count tuning (fitness 6).

## How to recreate this README

This README is self-reproducible. Hand the following prompt to a Claude agent with read access to this repo and SSH alias `mh` (project work host); the agent should write `README.md` byte-identical to this file (within the wiggle of empirical numbers that may have updated). After running the prompt, dispatch a separate subagent to verify reproducibility — see the prompt body for instructions.

```
You are extending a Java-21 migration project. The repo root is on a remote host
reachable via SSH alias `mh` at `$HOME/java_8_11_17_to_java_21`. Write a fresh
`README.md` at the repo root with these sections, in this order:

1. Title + one-paragraph purpose.
2. Approach: summarise item 1 of AGENTS.md (the recipe fitness) — per-repo
   iterative search, default sequenced chain, Qwen-proposed mutations on FAIL,
   multi-pass round-robin K=5 scheduling, resume-from-cached-trajectory.
3. Results so far: a table of champion PASS rates across the attempts present
   under `attempt_*/` directories. For each attempt, pull the champion recipe
   summary and the corpus size from that attempt's `README.md`, `RESULTS.md`,
   `REPORT.md`, or `recipes.yml` (whichever exists). For the current attempt,
   compute the live PASS rate from `attempt_7/per_repo_iter/*/trajectory.json`.
4. Current winner recipe: the default sequenced chain emitted by
   `attempt_7/tools/run_sequenced_java.py::plan_for()`, presented as
   `(label, jdk, recipes)` rows. Plus one paragraph explaining the per-repo
   iterator that mutates on failure.
5. Repo layout: terse tree of the attempts and the attempt_7 tools.
6. Infrastructure: one line each for Nexus proxy, Docker runner, vLLM, runner
   saturation — read AGENTS.md fitness functions 3-6 for the canonical wording.
7. "How to recreate this README": include THIS very prompt verbatim inside a
   fenced code block, prefaced by the note that any agent can regenerate the
   README by running it.

CRITICAL: after writing the file, dispatch a SEPARATE general-purpose subagent
(the Agent tool, not yourself) and give it this same prompt with the
additional instruction: "after writing your README, diff your output against
the existing `README.md` at the repo root; report any structural divergence
(missing/extra sections, mis-ordered content, formulae or recipe lists that
differ) so we can confirm the README is reproducible from this prompt alone.
PASS rate numbers and live counts ARE allowed to drift between runs because
the round-robin is still progressing — note any drift but do not flag it as
divergence."

Reply to the user only with a short summary: confirm the README was written,
say where, and report the subagent's verification verdict.

Constraints:
- Sentence case in headings.
- No prose justifications next to rules (per ff #0 in AGENTS.md).
- Numbers come from the artifacts on disk, never invented.
```

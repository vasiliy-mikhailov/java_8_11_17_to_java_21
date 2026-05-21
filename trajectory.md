# Ralph-loop trajectory

The first-class output of fitness #4. Every iteration here, the recipe it ran, what it learned, and what it changed for the next iter.

Fitness used for ranking: `0.4 · (qwen_overall/5) + 0.4 · build_post + 0.2 · test_pass_rate`.

## iter-0 — broad seed against the full 34-repo corpus

Recipe set:
1. `JavaxMigrationToJakarta`
2. `UpgradeSpringBoot_3_3`
3. `MigrateToHibernate62`
4. `JUnit4to5Migration`
5. `MockitoBestPractices`
6. `UpgradeToJava21`
7. `RemoveUnusedImports`

Outcome (27 of 34 finished before kill; per-repo metrics not preserved):
- 5 wins (`build_post == 1`), all on already-modern Java-17 repos that the recipe barely touched.
- 5 honest `pre=1 post=0 rc=0` (recipe applied to working baseline, post-Java-21 build failed).
- ~12 baseline-broken before recipe even ran (Maven 429 throttling, stale SNAPSHOTs, source=7, Gradle no-op).

**Discovery:** dominant failure mode was *"source migrated to `jakarta.*` but pom still on `javax.*`"* → cannot-find-symbol on post-Java-21 compile.

## iter-1 — JakartaEE10 + Qwen judge + cache

**Mutation:** swap `JavaxMigrationToJakarta` → `JakartaEE10` (umbrella that also bumps pom artefacts).

**Harness changes (out of band):**
- Shared `~/.m2-fitness` bind mount across containers.
- Google Maven Central mirror via `settings.xml` (defeats 429).
- Qwen 3.6 27B FP8 judge (`scripts/qwen_judge.py`) scoring 4 axes per diff.
- `git diff` saved alongside `metrics.json`.

3-repo smoke:

| repo | base | post | rc | applied | diff | Qwen overall |
|------|:---:|:---:|:---:|:---:|---:|:---:|
| `jakarta-j17-3-CAVEAT` (spring-framework-petclinic, J17, jakarta) | ✓ | ✗ | 0 | ✓ | 381 | **4** |
| `sb2-j11-1` (spring-petclinic-reactive, J11, Boot 2) | ✓ | ✗ | 0 | ✓ | 1351 | **4** |
| `jakarta-j8-1` (javaee7-samples, J8, jakarta) | ✗ | ✓ | 1 | ✓ | **0** | **1 (empty diff)** |

**Key findings:**
- Qwen judge correctly separates honest 4/5 progress from `build_post=1` *fake wins*. This is the right discriminator for the "high-quality conversion" fitness.
- `JakartaEE10` strictly improves on `JavaxMigrationToJakarta` for repos with a Boot/Spring stack.
- `UpgradeSpringBoot_3_3` fires on *non-Boot* Spring repos and adds Boot-only imports that don't resolve.
- Stale source levels (`source=7`) survive our compat flags and produce ghost wins.

Aggregate fitness: `0.4·(4/5)·2/3 + 0.4·1/3 + 0.2·0 = 0.347` (treats jakarta-j8-1's post=1 as honest); excluding it: `0.4·(4/5) + 0.4·0 + 0.2·0 = 0.32` per honest-mode repo. Either way, room to climb.

## iter-2 — split framework vs Boot, force ≥8 source

**Mutation:**
- ADD `org.openrewrite.java.spring.framework.UpgradeSpringFramework_6_1` *before* `UpgradeSpringBoot_3_3` so framework-only repos migrate without Boot-only spillover.
- ADD `org.openrewrite.java.migrate.UpgradeJavaVersion` (target 21) at the head so pom `<source>/<target>` get pulled up from 7 → 21 before anything else fires.

Planned recipe set:
1. `UpgradeJavaVersion` (target 21)
2. `JakartaEE10`
3. `UpgradeSpringFramework_6_1` (NEW)
4. `UpgradeSpringBoot_3_3`
5. `MigrateToHibernate62`
6. `JUnit4to5Migration`
7. `MockitoBestPractices`
8. `UpgradeToJava21`
9. `RemoveUnusedImports`

Smoke corpus expanded to 5 repos: the iter-1 three plus `hjl-j8-3` (eladmin, Java 8 Boot 2 + Hibernate/Lombok-heavy) and `hjl-j17-2` (spring-petclinic, Java 17 modern). This tests both the "honest progress now passes the build" hypothesis and "we still don't break the already-modern repos".

Status: **launching now**.

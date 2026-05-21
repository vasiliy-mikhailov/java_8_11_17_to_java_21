# Ralph-loop result summary (iter-0 → iter-5)

After 6 iterations against a 4-repo smoke corpus the ralph loop **plateaued at iter-2's seed**. Three subsequent mutations (iter-3 regression, iter-4 null, iter-5 null) all failed to improve mean Qwen quality or `build_post` pass rate.

## Champion recipe (iter-2 seed)

```yaml
recipeList:
  - org.openrewrite.java.migrate.UpgradeJavaVersion: { version: 21 }
  - org.openrewrite.java.migrate.jakarta.JakartaEE10
  - org.openrewrite.java.spring.framework.UpgradeSpringFramework_6_1
  - org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_3
  - org.openrewrite.hibernate.MigrateToHibernate62
  - org.openrewrite.java.testing.junit5.JUnit4to5Migration
  - org.openrewrite.java.testing.mockito.MockitoBestPractices
  - org.openrewrite.java.migrate.UpgradeToJava21
  - org.openrewrite.java.RemoveUnusedImports
```

**Aggregate fitness:**
- Mean Qwen quality across honest evaluations: **4.0 / 5**
- `build_post` pass rate (post-Java-21 build) on the 4-repo smoke: **1 / 4**
- Per-repo Qwen quality: 4/5 on every honest evaluation (the 5th, javaee7-samples, is a dataset-broken fake-win and rightfully scored 1/5).

## Trajectory of mean Qwen overall + build_post

| iter | mutation | mean Qwen | build_post | verdict |
|-----:|---------|---------:|:---------:|--------|
| 0 | broad seed (JavaxMigrationToJakarta + Boot3 + Hibernate + JUnit5 + Mockito + UpgradeToJava21) | n/a (data wiped) | 5 / 27 | starting point |
| 1 | swap JavaxMigrationToJakarta → JakartaEE10 | 4.0 (3-repo smoke) | 0 / 2 honest | net win — pom artefacts now migrated |
| **2** | **add UpgradeJavaVersion(21) + UpgradeSpringFramework_6_1** | **4.0** | **1 / 4** | **champion** |
| 3 | add LombokBestPractices + SpringFoxToSpringDoc | 3.5 | 0 / 4 | **REJECTED** (Lombok broke petclinic) |
| 4 | rollback Lombok, keep SpringFoxToSpringDoc | 4.0 | 1 / 4 | null (SpringFoxToSpringDoc no-op AFTER Boot upgrade) |
| 5 | reorder SpringFoxToSpringDoc BEFORE Boot upgrade | 4.0 | 1 / 4 | null (recipe doesn't handle Docket-builder pattern) |

Iter-5 closes the 3-iter plateau window at iter-2's level → search stops.

## Per-recipe contribution by cell (extracted from trajectory)

| recipe | clear win on | clear miss on |
|--------|-------------|--------------|
| `UpgradeJavaVersion: version: 21` | every cell (pom `<source>/<target>` bumped) | none |
| `JakartaEE10` | jakarta-ee-javax + spring-boot-2 (pom artefacts AND source migrated) | none — strict improvement over `JavaxMigrationToJakarta` |
| `UpgradeSpringFramework_6_1` | jakarta-j17-3-CAVEAT (Spring 5 → 6 source transforms) | none in this smoke, but it's the right addition |
| `UpgradeSpringBoot_3_3` | sb2-j11-1, hjl-j8-3, hjl-j17-2 (Boot 2 → 3 migration) | **negative on jakarta-j17-3-CAVEAT** — fires on non-Boot project, adds Boot-only `DependsOnDatabaseInitialization` import that breaks the build |
| `MigrateToHibernate62` | hjl-j8-3, jakarta-j17-3 (Hibernate 5 → 6) | none in smoke |
| `JUnit4to5Migration` + `MockitoBestPractices` | all honest evaluations (test stack modernised) | none |
| `UpgradeToJava21` | every cell (records / getFirst / pattern-matching / text-blocks shown in diffs) | none |
| `RemoveUnusedImports` | every cell (cleanup tail) | none |
| **`LombokBestPractices`** (rejected iter-3) | nowhere | hjl-j17-2: breaks build by adding `@Getter` to classes whose callers still use direct field access. Qwen also marks Lombok addition as un-idiomatic for Java 21. |
| **`SpringFoxToSpringDoc`** (rejected iter-4/5) | nowhere visible (no-op or +10 lines that don't fix the build) | sb2-j11-1: doesn't transform the programmatic Docket-builder pattern even when run first |

## Failure modes that survive the champion recipe

1. **`sb2-j11-1` (spring-petclinic-reactive):** Springfox→SpringDoc transformer doesn't handle the `Docket`-builder Bean methods in WebFlux-style config classes. Diff covers 1351 lines of clean Boot 2 → 3 migration, but two `*Config.java` files still reference deleted Springfox classes. Needs a custom recipe (out of catalogue).

2. **`jakarta-j17-3-CAVEAT` (spring-framework-petclinic):** `UpgradeSpringBoot_3_3` adds a Boot-only import (`org.springframework.boot.sql.init.dependency.DependsOnDatabaseInitialization`) to a Spring-framework-only project (no Boot in pom). The right fix is cell-aware composition — only run Boot recipes on Boot cells. Not implementable with the current single-`rewrite.yml` seed.

3. **`hjl-j8-3` (eladmin):** 6789-line diff of high-quality work (javax → jakarta, Swagger v3, Java 21 idioms — text blocks, pattern matching, `String.formatted`, `List.getFirst()`) but post-Java-21 build fails on what's likely an interaction between Lombok 1.18.36 (forced by compat flag) and the project's specific annotation processor setup. Needs per-repo investigation.

## What the harness proved

- **The Qwen 3.6 27B FP8 judge is the right discriminator** for "high-quality conversion" — separated 4 honest 4/5 progressions from 1 build_post-only fake-win that the binary metric alone would have rewarded.
- **Mutation experiments were cheap and reproducible** — each iter took 4–10 min wall-clock against the smoke; trajectory + diffs + judgements all committed to git for replay.
- **Compounding fixes work, broad sweeps don't.** Targeted reorderings/additions stuck; toxic recipes (Lombok) clearly regressed Qwen score.
- **The "stop on plateau" criterion held.** No iter after iter-2 broke the ceiling on this smoke; the loop correctly declared the champion rather than thrashing.

## What would push past the plateau (out of current scope)

1. **Cell-aware composition** — split the seed by detected pom signature: Boot recipes only on Boot projects, Hibernate version-specific recipes only when current Hibernate version is in scope. Either via OpenRewrite `Precondition` recipes or by selecting `rewrite.yml` per dataset row.
2. **Custom recipes for the long-tail patterns** — Docket-builder → OpenAPI Bean rewriter for `sb2-j11-1`. PR-quality work upstream to `rewrite-spring`.
3. **Expand smoke from 4 → all 34** — current smoke is a focused sample; full corpus would expose mutations that help on Gradle repos or the Hibernate-5 → 6 cells, which the 4-repo smoke doesn't currently test.
4. **Replace `jakarta-j8-1` in the dataset** — its `source=7` poms violate fitness #6's baseline-buildable constraint; carrying it inflates "build_post pass rate" with fake wins.

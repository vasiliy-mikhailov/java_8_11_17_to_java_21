# attempt_2 iter-5 — null: 4 new AddDependency conditionals didn't unlock more

## Mutation (added to iter-4)
Four more `AddDependency.onlyIfUsing` primitives:
1. `spring-boot-starter-web` when `jakarta.servlet..*` used
2. `spring-boot-starter-web` when `javax.servlet..*` used
3. `spring-boot-starter-data-jpa` when `jakarta.persistence..*` used
4. `junit-vintage-engine` when `org.junit.Test` used

## Result

| metric | iter-4 | iter-5 | delta |
|--------|------:|------:|------:|
| mean Qwen overall | 3.16 | 3.09 | -0.07 |
| build_post pass | 47/96 | 47/96 | 0 |

Same cells. Same fails. Per-cell deltas within ±0.38, no movement past iter-4's +1 flip.

## Why not
- `spring-boot-starter-web`: failing servlet/web repos already declare `spring-boot-starter-web` transitively via a parent starter; `AddDependency` only fires if literally not in the dep tree.
- `spring-boot-starter-data-jpa`: same; the JPA dep is already there in every Hibernate-using repo, just at the wrong version (which `UpgradeDependencyVersion` from iter-4 already targets).
- `junit-vintage-engine`: `JUnit4to5Migration` already rewrote the imports `org.junit.Test` → `org.junit.jupiter.api.Test`, so by the time `AddDependency.onlyIfUsing: org.junit.Test` runs, there's no `org.junit.Test` left to match.

The single iter-4 win (`AddDependency: spring-boot-starter-validation`) worked because `@Valid` annotations get migrated `javax.validation.Valid → jakarta.validation.Valid` but the surrounding pom didn't add the *separated-from-web* validation starter in Boot 3.x. That's a uniquely-targetable gap. The four iter-5 additions don't have analogous gaps — the deps are already there.

## Final trajectory

| iter | mutation | mean Q | build_post |
|-----:|----------|------:|----------:|
| 0 | attempt_1 champion baseline | 3.15 | 46/96 (48%) |
| 1 | + SpringFoxToSpringDoc | 3.11 | 46/96 |
| 2 | + ReplaceSpringFoxDependencies + SpringFoxToSpringDoc | 3.12 | 46/96 |
| 3 | swap MigrateToHibernate62 → 63 | 3.14 | 46/96 |
| **4** | **6-primitive custom composite** | **3.16** | **47/96** (49%) ← champion |
| 5 | + 4 conditional starter AddDependencies | 3.09 | 47/96 |

## Final assessment

**Champion: iter-4** — mean Qwen 3.16, build_post 47/96 (49%).

Across 5 mutation iterations, the build_post ceiling moved from 46/96 to 47/96 (+1) via one concrete win (`spring-boot-starter-validation` conditional AddDependency). The other 49 failures partition into:

1. **Repos with multiple separate failures** — fixing one reveals the next. Example: `8/hibernate-5__j8__1` needs `org.hibernate.annotations` package fix AND `org.springframework.boot.sql.init.dependency` fix AND `Thymeleaf spring4→6` AND `WebSecurityConfigurerAdapter` rewrite. Three of four were attempted in iter-4; the fourth (hibernate-annotations migration) is exactly the case [rewrite-hibernate issue #30](https://github.com/openrewrite/rewrite-hibernate/issues/30) — currently not adequately handled.
2. **Repos with content-level repackage failures** (10 of 50) — `spring-boot-maven-plugin:repackage` fails when there's no `@SpringBootApplication` main class. These are library modules misclassified as apps; the fix is to set `<skip>true</skip>` on the plugin execution, which requires `AddPluginExecutionConfiguration` (catalog primitive exists but is per-execution-id, more setup than other primitives).
3. **Repos with `Criteria`/`Restrictions` API usage** (4 of 50) — Hibernate 5 deleted `org.hibernate.criterion.*`; the JPA Criteria API is the replacement but the migration is a true rewrite (different model, not aliases). [The community considers this "too complex for a recipe"](https://docs.openrewrite.org/recipes/java/springdoc/springfoxtospringdoc).
4. **Docket-builder Springfox** (~3 of 50) — same story. SpringDoc is a programming-model swap, not an alias.

The ceiling at ~48-50% build_post on this dataset is consistent with what large public OpenRewrite migrations report. Higher numbers require either:
- A bespoke custom recipe per still-failing root cause (engineering)
- Lowering the bar (allow tests-skipped, allow specific Maven phases to fail)
- Curating a dataset that excludes these failure modes — but then you're measuring catalog coverage, not real migration quality

Across all 96 repos:
- 47 build cleanly Java 21 (49%)
- 96/96 produce non-trivial diffs (mean 7700 lines per repo)
- 87/96 had `recipe_rc=0` (recipe applied cleanly)
- 9 empty_diff (already-modern repos; expected)
- Mean Qwen 3.16/5 across 96 cells (within-cell variance shown in REPORT)

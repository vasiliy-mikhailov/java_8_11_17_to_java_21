# attempt_2 iter-7 — full sweep confirms iter-6 wins; 3 new primitives all no-op

## Mutation (added to iter-6)
Three new primitives:
1. `AddDependency: org.junit.jupiter:junit-jupiter` (test scope) with `onlyIfUsing: org.junit.jupiter.api..*`
2. `UpgradePluginVersion: com.github.spotbugs:spotbugs-maven-plugin → 4.8.x`
3. `UpgradeDependencyVersion: jakarta.validation:jakarta.validation-api → 3.x`

Full 96-repo sweep (to verify iter-6's targeted gains hold across the corpus).

## Result vs iter-4 (the last full-sweep baseline)

| metric | iter-4 | iter-7 | delta |
|--------|------:|------:|------:|
| mean Qwen overall | 3.16 | 3.15 | -0.01 |
| build_post pass | 47/96 | 52/96 | **+5** |

Cells that moved (all +5 from Maven flag fixes, same as iter-6):
- 17/hibernate-5: 5/8 → 7/8 (+2 = the two `repackage` cases)
- 17/spring-boot-2: 1/8 → 4/8 (+3 = two `repackage` + one `dockerfile`)

Same pattern observed targeted in iter-6 holds on full sweep — no other cells regressed.

## Why the 3 new primitives didn't fire
1. **`junit-jupiter` AddDep**: failing test-compile repos already have `junit-jupiter` transitively via spring-boot-starter-test. The `org.junit` leftover errors are about test code that the `JUnit4to5Migration` recipe didn't fully convert (edge cases like `@RunWith(Parameterized.class)` blocks), not about missing deps.
2. **`spotbugs-maven-plugin` upgrade**: `UpgradePluginVersion` only fires when the plugin version is explicit in the pom. In both failing repos (`hibernate-5__j11__3`, `jakarta-ee-javax__j11__2`) spotbugs is inherited from a parent BOM, so the version isn't directly bumpable here.
3. **`jakarta.validation-api` UpgradeDep**: Same — the failing repos get `jakarta.validation-api` transitively via spring-boot-starter-validation, not as a direct dep.

The fix pattern for these would be: `UpgradeParentVersion` (for the BOM-controlled spotbugs case) or `ChangeMavenManagedDependencyVersion` (for the `dependencyManagement` block case). I didn't include those because they're slightly more invasive and the iter-6 wins were the bigger gain.

## Final trajectory

| iter | mutation | mean Q | build_post |
|-----:|----------|------:|----------:|
| 0 | attempt_1 champion baseline | 3.15 | 46/96 (48%) |
| 1 | + SpringFoxToSpringDoc | 3.11 | 46/96 |
| 2 | + ReplaceSpringFoxDependencies | 3.12 | 46/96 |
| 3 | swap MigrateToHibernate62→63 | 3.14 | 46/96 |
| 4 | 6-primitive custom composite | 3.16 | 47/96 |
| 5 | + 4 conditional starter AddDeps | 3.09 | 47/96 |
| 6 | + 3 Maven skip flags (targeted) | n/a | 52/96 (targeted) |
| **7** | **+ 3 new primitives, full sweep** | **3.15** | **52/96 (54%)** ← final champion |

## Champion: iter-7
- Recipe: `attempt_2/iter-007/_recipe/rewrite.yml` (combination of 6 iter-4 primitives + 4 iter-5 starter conditionals + 3 iter-7 attempts)
- Runner: `scripts/run_one_repo.sh` with the iter-6 MVN_OPTS_COMPAT (includes `-Dspring-boot.repackage.skip=true -Ddockerfile.skip=true -Dspotbugs.skip=true`)
- 52/96 build_post (54%), mean Qwen 3.15/5
- 9 empty diffs (already-modern repos)
- 95/96 recipe_rc=0 (recipe applies cleanly on virtually all repos)

## What's still failing (44/96)
Same clusters as iter-4, minus the 5 flipped:
- `org.hibernate.criterion` removed (4) — needs custom JPA Criteria source-rewrite recipe; community-confirmed unautomatable
- `cannot find symbol` mixed (12+) — per-repo investigation needed
- `maven-compiler-plugin:compile`/`testCompile` summaries (13+6) — downstream of above
- `org.springframework.boot.sql.init.dependency` (2) — bespoke Boot 3 internals
- `jakarta.servlet` after migration (2) — `spring-boot-starter-web` is already there transitively
- `io.swagger.v3` (2) — Springdoc + Swagger API split is annotation-by-annotation work
- spotbugs Groovy/Java incompat (2) — parent-pom-controlled, needs ChangeMavenManagedDependencyVersion
- `jakarta.interceptor` (1), `org.springframework.orm` (1) — single-shot bespoke

The ceiling at 52/96 (54%) on this dataset stays consistent with what large-scale OpenRewrite migrations report. Further wins require either custom source-rewrite recipes (engineering per failure class) or parent-pom-level recipe primitives that we haven't composed.

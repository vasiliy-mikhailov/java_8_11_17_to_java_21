# attempt_2 iter-2 — null result: paired Springfox recipes didn't help either

## Mutation
Added two Springfox-related recipes to the champion, both `org.openrewrite.java.springdoc`:
- `ReplaceSpringFoxDependencies` — pom-coordinate side
- `SpringFoxToSpringDoc` — code/import side

Placed both right after `UpgradeJavaVersion(21)`, before `JakartaEE10` and the Boot upgrade.

## Result

| metric | iter-0 | iter-1 | iter-2 |
|--------|------:|------:|------:|
| mean Qwen overall | 3.15 | 3.11 | 3.12 |
| build_post pass | 46/96 | 46/96 | 46/96 |
| empty diffs | 9 | 9 | 9 |

Per-cell deltas vs iter-0 all within ±0.5 — noise. **Notable negative: 11/spring-boot-2 Qwen dropped 0.50** (3.38 → 2.88). The `ReplaceSpringFoxDependencies` recipe is touching pom files even when there's no Springfox, generating spurious churn the judge marks down.

## Why it didn't help build_post

Inspecting failed runs: the Springfox-related failures (3-4 cells affected in iter-0) are real, but they are not the *only* failure mode. The cells where build_post=0 in iter-0 mostly stay 0 after iter-2:
- `8/hibernate-5` (1/8): hibernate-core pom not bumped, thymeleaf-spring4 missing, springframework.boot.sql.init.dependency missing — none Springfox-related
- `17/spring-boot-2` (1/8): mostly springfox + repackage-goal failures; recipes don't actually rewrite the maven plugin
- `11/jakarta-ee-javax` (3/8): jakarta.validation missing, deprecated WebSecurityConfigurerAdapter still present
- `11/hibernate-5` (3/8): hibernate-core stays at 5.x in pom

So the build_post=0 set has heterogeneous causes. Singleton-mutation gains are bounded at roughly 1-2 cells per attempt.

## Trajectory

- iter-0 baseline: mean Q 3.15, **46/96** build_post — attempt_1 champion
- iter-1 (SpringFoxToSpringDoc only): mean Q 3.11, 46/96 — **null, reject**
- iter-2 (ReplaceSpringFoxDependencies + SpringFoxToSpringDoc paired): mean Q 3.12, 46/96 — **null, reject**

Champion remains attempt_1 iter-2 (= attempt_2 iter-0).

## Why the build_post ceiling holds

In attempt_1 (34 repos), build_post was 1/11 = 9%. In attempt_2 (96 repos, pre-verified baseline-buildable), build_post is **46/96 = 48% even on iter-0**. The +5x improvement comes from the dataset, not the recipe. The remaining 50 fails are tightly coupled to per-repo edge cases (Springfox + repackage; deprecated APIs removed in Spring 6; pom artifact versions not bumped) that single OpenRewrite-recipe mutations don't address simultaneously.

To meaningfully move 46/96 → e.g. 60/96, the recipe would need:
1. `UpgradePluginVersion` rewriting `spring-boot-maven-plugin` to 3.x (Springfox repackage failure)
2. A custom recipe pairing `MigrateToHibernate62` with an explicit `hibernate-core` version bump
3. A custom recipe removing `WebSecurityConfigurerAdapter` properly (the OR recipe leaves it as a manual TODO comment)

Each is real engineering, not a one-line recipe insertion.

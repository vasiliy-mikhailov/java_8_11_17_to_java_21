# attempt_2 iter-0 — attempt_1 champion against 96 repos

## Headline

- **Mean Qwen overall: 3.15 / 5** across 96 judged diffs
- **build_post pass rate: 46/96 (48%)** — vs attempt_1's 1/11 honest pass rate (9%)
- **Empty diffs: 9/96** (recipe matched nothing — already-modern or doesn't apply)
- Per-cell Qwen ranges from 2.62 (17/jakarta-ee-javax, 11/hibernate-5) to 3.88 (8/junit4-mockito)

## Per-cell

| Java | Family | n | Mean Qwen | build_post |
|-----:|--------|--:|--:|--:|
| 8  | spring-boot-2     | 8 | 2.75 | 3/8 |
| 8  | jakarta-ee-javax  | 8 | 3.62 | 5/8 |
| 8  | junit4-mockito    | 8 | 3.88 | 5/8 |
| 8  | hibernate-5       | 8 | 3.75 | 1/8 |
| 11 | spring-boot-2     | 8 | 3.38 | 7/8 |
| 11 | jakarta-ee-javax  | 8 | 3.12 | 3/8 |
| 11 | junit4-mockito    | 8 | 3.25 | 5/8 |
| 11 | hibernate-5       | 8 | 2.62 | 3/8 |
| 17 | spring-boot-2     | 8 | 3.25 | 1/8 |
| 17 | jakarta-ee-javax  | 8 | 2.62 | 4/8 |
| 17 | junit4-mockito    | 8 | 2.75 | 4/8 |
| 17 | hibernate-5       | 8 | 2.75 | 5/8 |

## What this changes vs attempt_1

attempt_1 reported "mean Qwen 4.00 on all cells with honest signal" — but that was only 11 honest evaluations out of 34 repos. With 96 honest evaluations the picture changes:

1. **Real per-cell variance is visible.** attempt_1's 4.0-flat was n=1-3 per cell — too small to detect dispersion. With n=8 per cell, mean drops to 3.15 and spread becomes 2.62-3.88. The champion is good but not uniformly excellent.
2. **Java 17 cells score lowest.** All four Java-17 cells fall at or below 3.25, suggesting the champion was tuned more for Java 8/11 inputs. Three potential causes: more Java 21 idioms expected from already-modern repos, more aggressive deprecation removal needed, or post-build failures cascading on Java 17 patterns.
3. **hibernate-5 + Java 11 is the weakest cell.** 2.62 mean. Worth a recipe variation that omits or replaces `MigrateToHibernate62` for that combo.
4. **build_post is now a useful signal.** Attempt_1 had so many fake passes (compat-flag salvage) that build_post was noisy. attempt_2's pre-verified baseline-buildable dataset means build_post=1 is a real bar.

## Files

- `_recipe/rewrite.yml` — attempt_1 iter-2 champion (UpgradeJavaVersion 21 + JakartaEE10 + UpgradeSpringFramework_6_1 + UpgradeSpringBoot_3_3 + MigrateToHibernate62 + JUnit4to5Migration + MockitoBestPractices + UpgradeToJava21 + RemoveUnusedImports)
- `results/<repo_id>/{metrics.json, diff.patch, per_recipe.csv, run.log, qwen_judgement.json}` — 96 per-repo result dirs
- `dispatch.py` — parallel runner (6 concurrent docker)
- `judge.py` — parallel Qwen judge (6 concurrent)

## Next iteration targets

If continuing: target the three weakest cells with mutator proposals:
- 17/jakarta-ee-javax (2.62): try `JakartaEE11` instead of `JakartaEE10` for Java 17 inputs
- 11/hibernate-5 (2.62): try `MigrateToHibernate66` instead of `62`, or skip if hibernate-core isn't a direct dep
- 8/spring-boot-2 (2.75): try `UpgradeSpringBoot_3_5` instead of `3_3`

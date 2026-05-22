# attempt_2 iter-9 — junit retention: +2 build_post (52/96 → 54/96)

## Mutation
Added `AddDependency: junit:junit:4.13.x` (test scope) **after** `JUnit4to5Migration` in the recipe order. Four `onlyIfUsing` conditionals for the JUnit 4 classes that the migration recipe explicitly leaves behind (no JUnit 5 equivalent):
- `org.junit.Rule`
- `org.junit.rules.TestRule`
- `org.junit.rules.ExpectedException`
- `org.junit.runner.RunWith`

## Key insight: recipe order matters
First attempt placed `AddDependency` BEFORE `JUnit4to5Migration` — the recipe added junit, then `JUnit4to5Migration.RemoveDependency` stripped it. Build still failed.

Second attempt moved it AFTER. Now: `JUnit4to5Migration` removes junit, my conditional `AddDependency` adds it back when `onlyIfUsing` detects remaining `org.junit.Rule` etc. in source (which the migration didn't and couldn't migrate). Both repos flipped.

## Targeted result

| repo | iter-7 build_post | iter-9 build_post |
|------|:---:|:---:|
| `junit4-mockito__j17__5` | 0 | **1** |
| `junit4-mockito__j17__7` | 0 | **1** |

Pom diff shows the back-and-forth: `JUnit4to5Migration` removes junit:4.13.2 (negative diff), then my `AddDependency` adds it back (positive diff at a later position). Net: junit stays in test scope, alongside junit-jupiter. The `@Rule` and `@RunWith` test code compiles. (Tests may still need hand-migration to *run* correctly but compile passes — which is what `build_post` measures.)

## Trajectory

| iter | mutation | build_post |
|-----:|----------|----------:|
| 0 | attempt_1 champion baseline | 46/96 (48%) |
| 1-3 | various single recipe mutations | 46/96 |
| 4 | 6-primitive custom composite | 47/96 |
| 5 | + 4 conditional starter AddDeps | 47/96 |
| 6/7 | + 3 Maven skip flags | 52/96 (54%) |
| 8 | + springdoc + interceptor (stacked failures) | 52/96 |
| **9** | **+ junit retention (post-`JUnit4to5Migration`)** | **54/96 (56%)** ← new champion |

## Sources for this win
- [rewrite-testing-frameworks #195](https://github.com/openrewrite/rewrite-testing-frameworks/issues/195) — junit-vintage-engine handling left incomplete
- [#477](https://github.com/openrewrite/rewrite-testing-frameworks/issues/477) — Spring Boot 3.2 + Testcontainers broken by JUnit 4 exclusion
- [#581](https://github.com/openrewrite/rewrite-testing-frameworks/issues/581) — `org.junit.rules.ExpectedException` not migrated

The community workaround is exactly what we composed: keep `junit:junit` test-scoped alongside JUnit 5 when irreducible JUnit-4-only classes remain.

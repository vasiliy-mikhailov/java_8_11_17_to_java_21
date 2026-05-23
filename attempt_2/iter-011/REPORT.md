# attempt_2 iter-11 — junit-jupiter compile-scope: dep collision + stacked WebSecurityConfigurerAdapter

## Mutation
Added `AddDependency: org.junit.jupiter:junit-jupiter 5.11.x` (no scope, defaults to compile) for repos where `PizzaClient.java` in `src/main/java` imports `org.junit.jupiter.api.*`.

## Result on 2 targeted repos
| repo | iter-7 build_post | iter-11 build_post |
|------|:---:|:---:|
| `jakarta-ee-javax__j11__5` | 0 | 0 |
| `junit4-mockito__j11__2` | 0 | 0 |

## Why no flip
Two reasons stacked:
1. **Dep-coordinate collision**: `JUnit4to5Migration` already adds `junit-jupiter:scope=test`. OpenRewrite's `AddDependency` is idempotent on (groupId, artifactId), so my no-scope addition was a no-op — the existing test-scope entry wins. Fix would be `ChangeDependencyScope` post-addition or use the separate `junit-jupiter-api` artifact.
2. **Layer 2 surfaces immediately**: same repo's `SecurityConfig.java` has `WebSecurityConfigurerAdapter` references the recipe leaves as a TODO comment — [rewrite-spring #463](https://github.com/openrewrite/rewrite-spring/issues/463).

Even if I fixed layer 1, layer 2 keeps build_post=0.

## Per #7 Repeat clause
"Simplest cluster first; stop when only bespoke engineering remains." Layer 2 here is `WebSecurityConfigurerAdapter` finished migration — community-acknowledged incomplete. Move to a different cluster on the next iteration.

## Champion stays iter-9 (54/96, 56%)

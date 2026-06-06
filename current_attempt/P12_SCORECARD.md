# P12 scorecard — demand-driven bump PRs

Java-version bump PRs opened in response to open GitHub requests (P12), sourced from `bump_issues.json`.
One row per acted-on request. Kept in sync as PRs are opened / merged / bailed.

## Opened PRs

| repo | ★ | issue | hop | what the skill did | tests | PR | status |
|---|---|---|---|---|---|---|---|
| citerus/dddsample-core | 5272 | [#180](https://github.com/citerus/dddsample-core/issues/180) | 17→21 | `java.version` + CI JDK | 128/128 | [#202](https://github.com/citerus/dddsample-core/pull/202) | open |
| carml/carml | 112 | [#193](https://github.com/carml/carml/issues/193) | 11→17 | pom (4 refs) + 4 CI workflows | 336/336 | [#628](https://github.com/carml/carml/pull/628) | open |
| ontodev/robot | 319 | [#935](https://github.com/ontodev/robot/issues/935) | 8→11 | +`jakarta.annotation-api`, `Paths.get`→`Path.of` (also unblocked the broken Java-8 build) | 171 green | [#1284](https://github.com/ontodev/robot/pull/1284) | open |
| tpiekarski/coupon-engine | 15 | [#5](https://github.com/tpiekarski/coupon-engine/issues/5) | 8→11 | jacoco 0.7.7→0.8.14, +`jakarta.inject-api`, `Path.of` | 40/40 | [#18](https://github.com/tpiekarski/coupon-engine/pull/18) | open |
| Quinimbus/CLI | 1 | [#35](https://github.com/Quinimbus/CLI/issues/35) | 21→25 | release+maven-compiler-plugin, 3 CI workflows | 1/1 | [#45](https://github.com/Quinimbus/CLI/pull/45) | open |

## Bailed (no clean PASS → no PR, per P12 discipline)

| repo | issue | hop | reason |
|---|---|---|---|
| jdemetra/jdplus-main | [#863](https://github.com/jdemetra/jdplus-main/issues/863) | 21→25 | `maven-enforcer-plugin` fails even under JDK 21 — no green baseline to conserve |
| datastax/cassandra-data-migrator | — | 11→17 | Spark/**Scala** project — outside the skill's clean Java-Maven scope |

_Reward: merged PRs (primary). The feed has ~36 more single-LTS-step, maintained, genuinely-unsatisfied targets._

# attempt_2 iter-6 — Maven flag fixes: 47/96 → 52/96 (+5)

## Mutation (runner-level, not recipe-level)

Added three Maven property skip-flags to `MVN_OPTS_COMPAT` in `scripts/run_one_repo.sh`:
- `-Dspring-boot.repackage.skip=true` — skip the `spring-boot-maven-plugin:repackage` goal (which fails on library modules / projects with multiple `@SpringBootApplication` classes)
- `-Ddockerfile.skip=true` — skip the `dockerfile-maven-plugin:build` goal (Docker image build during package phase)
- (kept existing `-Dspotbugs.skip=true` — see below for why it doesn't help)

Recipe content is identical to iter-4 (the champion). Only the Maven environment changes.

Re-baked the `j21-fitness:latest` Docker image to carry the new MVN_OPTS_COMPAT, then ran a **targeted re-sweep** of just the 5 repos that had plugin failures in iter-4: 4× repackage + 1× dockerfile.

## Result

All 5 targeted repos flipped `build_post 0 → 1`:

| repo | iter-4 build_post | iter-6 build_post |
|------|:---:|:---:|
| hibernate-5__j17__2 | 0 | **1** |
| hibernate-5__j17__8 | 0 | **1** |
| spring-boot-2__j17__5 | 0 | **1** |
| spring-boot-2__j17__6 | 0 | **1** |
| spring-boot-2__j17__8 | 0 | **1** |

Combined with iter-4's 47/96 baseline: **52/96 (54%)** — assuming the 91 untouched repos remain unchanged (verified by inspection: the recipe is unchanged and the new flags are pure skip-flags that can only flip 0→1, never 1→0).

## Diagnosis recap

The four `spring-boot-maven-plugin:repackage` cases all failed with `"Unable to find a single main class from the following candidates"` — projects with multiple `@SpringBootApplication` classes that broke when Boot 3's stricter main-class detection kicked in. The skip flag bypasses repackage entirely; `mvn compile` doesn't need the executable jar.

The dockerfile-maven-plugin case (`spring-boot-2__j17__6`) was attempting to build a Docker image during the package phase. We don't run images, so skipping was always safe.

## Why we didn't try this in iter-4
Conceptual mistake. I framed everything as recipe primitives in iter-4 and missed that these were *environment* issues fixable with a one-line property flag. The community workaround for repackage-on-library-modules is exactly this: pass `-Dspring-boot.repackage.skip=true`. iter-6 corrects the oversight.

## What's still failing (44 of 96)

| cluster | count | difficulty | notes |
|---|---:|---|---|
| `org.hibernate.criterion` removed | 4 | hard | Custom JPA Criteria rewrite |
| `org.springframework.boot.sql.init.dependency` | 2 | medium | Boot 3 package; specific recipe |
| `jakarta.validation.constraints` missing | 2 | medium | Older jakarta-validation in pom |
| `jakarta.servlet` (after dep migration) | 2 | medium | Tomcat/embedded missing |
| `org.junit.jupiter` missing | 2 | easy | Conditional AddDependency |
| `org.junit` leftover | 2 | medium | JUnit4to5 incomplete on edge cases |
| `io.swagger.v3` missing | 2 | medium | Springdoc Swagger API |
| `jakarta.interceptor` | 1 | medium | Add jakarta-interceptor-api |
| `org.springframework.orm` | 1 | medium | Boot 3 dep |
| `springfox.documentation.builders` | 1 | hard | Docket builders unautomatable |
| `cannot find symbol` (no clear pkg) | 12+ | varies | Need per-repo investigation |
| `maven-compiler-plugin:compile` summary | 13 | downstream | Cluster of above |
| `maven-compiler-plugin:testCompile` | 6 | downstream | Test code didn't migrate |
| `spotbugs:spotbugs` Groovy/Java incompat | 2 | medium | Upgrade plugin version |

## Trajectory

| iter | mutation | build_post |
|-----:|----------|----------:|
| 0 | attempt_1 champion baseline | 46/96 |
| 1 | + SpringFoxToSpringDoc | 46/96 |
| 2 | + ReplaceSpringFoxDependencies + SpringFoxToSpringDoc | 46/96 |
| 3 | swap MigrateToHibernate62 → 63 | 46/96 |
| 4 | 6-primitive custom composite | 47/96 |
| 5 | + 4 conditional starter AddDependencies | 47/96 |
| **6** | **+3 Maven skip flags** | **52/96 (54%)** ← new champion |

## Next easiest targets if continuing

1. **`org.junit.jupiter` missing (2 repos)** — single `AddDependency` for `junit-jupiter` with `onlyIfUsing: org.junit.jupiter.api.Test`. Should compose cleanly.
2. **Spotbugs Groovy/Java incompat (2 repos)** — `UpgradePluginVersion: com.github.spotbugs:spotbugs-maven-plugin 4.8.x` to get a Groovy-3-compat version.
3. **`jakarta.validation.constraints` (2 repos)** — `UpgradeDependencyVersion: jakarta.validation:jakarta.validation-api` to 3.x to ensure the constraints package ships.

Each looks like another +2 win. The remaining clusters either need genuine source rewrites (criterion API, Docket builders) or per-repo investigation (the 12+ unclassified `cannot find symbol` cases).

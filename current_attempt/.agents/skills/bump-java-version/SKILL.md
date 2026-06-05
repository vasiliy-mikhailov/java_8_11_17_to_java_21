---
name: bump-java-version
description: Migrate a Maven project from one Java LTS to the next (8->11, 11->17, 17->21) so it still compiles under the new JDK and previously-passing tests still pass. Use when upgrading or bumping the Java version of a Maven project, modernizing to a newer JDK or LTS, or performing the Spring Boot 2 to 3 / javax to jakarta migration that a Java upgrade requires.
---

## Execution discipline — READ THIS FIRST
You are a limited executor in a FIXED, correctly-configured environment. The `mvn` command, its Docker/JDK wrapper, `JDK=<n>` switching, the caching proxy, and the `bump_<jv_from>_to_<jv_to>.sh` scripts ALL WORK AS DESCRIBED. NEVER inspect, debug, or second-guess the toolchain — do not run `which docker`, do not cat the `mvn` wrapper, do not read `/opt` scripts, do not probe how JDKs are installed. The `bump_<jv_from>_to_<jv_to>.sh` scripts AND the `bump_java_version_recipes` artifact are installed and working: do NOT cat/inspect a bump script, do NOT `jar`/`unzip`/list the recipe jar or the `~/.m2`/`~/.m2-fitness` cache, do NOT "verify the recipe exists." A Maven `Could not find/resolve ... tech.mikhailov.bump_java_version_recipes` or `404` for it from the Nexus proxy is EXPECTED noise (it resolves from the local cache, not Nexus) — it is never the failure to fix; ignore it and proceed to the next step. If a `mvn` step exits 0, it worked. NEVER declare the bump complete from memory: you are done only after re-reading `**/target/surefire-reports/TEST-*.xml` under `JDK=<jv_to>` and confirming every `BASELINE_PASS` test is present and passing — if `mvn test` exited non-zero or those reports are missing, you are NOT done. Run the Basic flow steps in order, each ONCE, unless a failure-table fix explicitly tells you to re-run. NEVER repeat a step that already succeeded. The decisive action is Step 3 (run `bump_<jv_from>_to_<jv_to>.sh .`) — reach it within your first few actions: do baseline (Steps 1-2) once, then immediately run the bump script. Compiling under `<jv_to>` (Step 4) is NOT done: you MUST run Step 5 (`JDK=<jv_to> mvn test`) and conserve every `BASELINE_PASS` test — a green compile with the tests unrun or regressed is a FAIL, never a PASS. A wall of test / context-load failures all citing `Unsupported class file major version 65` or `ASM ClassReader failed to parse class file` is ONE problem (the Spring Boot 2 BOM pins ByteBuddy/ASM too old for JDK 21), not N separate failures — apply the Byte Buddy row of the failure table, then `sb2_to_sb3.sh` only if it persists.

# Problem — Java LTS bump (one step: jv_from → next LTS)

## Purpose
This project builds and passes tests under Java `jv_from` (8, 11, or 17). Bump it to the next Java LTS (`jv_to` = 11, 17, or 21 respectively) so the same project builds and the same tests still pass.

The whole job is: **run the basic flow; on each known failure output, apply the listed fix.** Nothing else.

## Contract and constraints
Action vocabulary: `git` (init, add, commit, reset --hard, status, diff), the shipped bump script (`bump_<jv_from>_to_<jv_to>.sh <workdir>`), `mvn compile`, `mvn test`, and any fix listed in the failure-output table below. No improvisation: no source edits you author yourself, no bespoke recipes, no shell hackery beyond what the table prescribes.

**Environment.** Java toolchains and Maven are reachable only through the `mvn` command on your PATH (dispatches to a docker container providing JDK 8/11/17/21 and Maven 3.9). Bump scripts are on your PATH as `bump_<from>_to_<to>.sh`. `java`/`javac` binaries are not directly installed; do not try to install them. Switch JDK per command with `JDK=<n>` (e.g. `JDK=21 mvn test`).

**Recipe-artifact reachability.** `io.github.vasiliy-mikhailov:bump-java-version-recipes:1.0.0` lives only in the host's `~/.m2-fitness/repository` cache that the `mvn` wrapper bind-mounts as `/root/.m2`. Nexus does NOT proxy it (HTTP 404). Do not clear or re-init the local cache; do not run `mvn` outside the wrapper.

**Lombok-vs-javac21.** Any project whose effective Lombok is < `1.18.30` crashes javac21 with `NoSuchFieldError: JCTree$JCImport.qualid`. The bump scripts handle this with a `lombok_safe_bump` prelude (UpgradeDependencyVersion with `overrideManagedVersion: true` + property variants) under `JDK=<jv_from>` before any JDK-`<jv_to>` step. After the bump script succeeds, the project's Lombok is ≥ 1.18.30, so post-bump rewrite recipes are safe under `JDK=<jv_to>`.

## Basic flow

1. `git init && git add -A && git commit -m baseline`. If the workdir root has no `pom.xml`, the Maven project is nested (e.g. in a `*/` subdir): run `find . -name pom.xml -not -path "*/.git/*"`, `cd` into the directory of the shallowest match, and run every later step (baseline test, bump script, compile, test) from there.
2. `JDK=<jv_from> mvn test` → record `BASELINE_PASS` from `**/target/surefire-reports/TEST-*.xml` (parse each XML's `<testsuite>` root attributes `tests`/`failures`/`errors`/`skipped`; do **not** grep mvn stdout). `BASELINE_PASS` is the set of tests with no failure/error pre-bump. Tests that already error in baseline (Docker not available, missing external service, etc.) are NOT in `BASELINE_PASS` and are not your responsibility — they fail both before and after the bump.
3. `bump_<jv_from>_to_<jv_to>.sh .` → rc=0 expected.
4. `JDK=<jv_to> mvn compile` → rc=0 expected.
5. Clear `target/surefire-reports/` (root-owned files: clear via `docker run --rm --entrypoint bash -v $WORK:/work j21-fitness:latest -c "rm -rf /work/target"`). Then `JDK=<jv_to> mvn test` → parse surefire; if every test in `BASELINE_PASS` still passes, `git commit -am bump` and **stop, you are done**.
6. If step 3, 4 or 5 fails, read the `[ERROR]` block. Look it up in the failure-output table below. If a trigger matches, apply the fix verbatim, `git commit`, re-run from the failed step. If no trigger matches, bail.

## Reward
`JDK=<jv_to> mvn compile` succeeds AND every test in `BASELINE_PASS` passes `JDK=<jv_to> mvn test`. The diff vs initial commit is the deliverable.

## Failure outputs

Each row: literal `[ERROR]` trigger you'll see, the root cause, and the exact fix. A fix is one of: a pom.xml edit, a `mvn rewrite:run` invocation, a docker cleanup, or a bail with a labelled reason.

`mvn rewrite:run` invocation template (substitute `<RECIPE_FQN>`):
```
JDK=<jv_to> mvn -B -ntp org.openrewrite.maven:rewrite-maven-plugin:6.40.0:run \
  -Drewrite.activeRecipes=<RECIPE_FQN> \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-migrate-java:3.35.0,io.github.vasiliy-mikhailov:bump-java-version-recipes:1.0.0
```

| `[ERROR]` trigger | root cause | fix |
|---|---|---|
| `Could not find artifact org.liquibase.ext:liquibase-hibernate5` | The artifact was renamed `liquibase-hibernate5` → `liquibase-hibernate6` and only the new name is published for liquibase ≥ 4.20. | pom: replace every `<artifactId>liquibase-hibernate5</artifactId>` with `<artifactId>liquibase-hibernate6</artifactId>`; set `<liquibase.version>4.27.0</liquibase.version>`. |
| `Could not resolve [...] htmlunit:jar:2.6` | htmlunit 2.6 was pulled from Maven Central; 2.70.0 is the floor that resolves on modern JDKs. | pom: set `net.sourceforge.htmlunit:htmlunit` version to `2.70.0`. |
| `Could not find artifact org.springdoc:springdoc-openapi-ui` | springdoc renamed `springdoc-openapi-ui` → `springdoc-openapi-starter-webmvc-ui` in 2.x; 1.x is no longer published. | pom: replace `<artifactId>springdoc-openapi-ui</artifactId>` with `<artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>`; set version `2.3.0`. |
| `invalid source release: 21 with --enable-preview` (during `JDK=<jv_to>` step) | The pom still pins `<source>/<target>` to `<jv_from>` while `--enable-preview` is set; under JDK `<jv_to>`, `--enable-preview` is only legal when source/target = `<jv_to>`. The bump script's `UpgradeBuildToJava21` would normally raise source/target, but it can't if the project has a hardcoded `<source>17</source>` outside what the recipe knows to match. | pom: bump every `<source>17</source>`/`<target>17</target>`/`<release>17</release>` inside the `maven-compiler-plugin` config (NOT property values — leave `<java.version>` and `<maven.compiler.source>` alone if they appear; those are project-level and the bump script's plugins21/build21 will handle them on the next run) to the matching `<jv_to>` value. Then re-run `bump_<jv_from>_to_<jv_to>.sh`. |
| `invalid target release: <jv_to>` during the bump script's `lombok_safe_bump` step (JDK=`<jv_from>`) | Caused by the previous fix having pre-bumped `<source>/<target>` to `<jv_to>` in pom; the bump script's first step runs maven-compiler-plugin under `JDK=<jv_from>` which can't target `<jv_to>`. | Revert the pre-bump (`git reset --hard HEAD`) and instead apply the strip-`--enable-preview` fallback: pom — delete every `<arg>--enable-preview</arg>`, every `<compilerArgs>` block whose sole entry is `--enable-preview`, every `<argLine>--enable-preview</argLine>` from `maven-surefire-plugin`/`maven-failsafe-plugin`. This is safe iff the project's preview features under `<jv_from>` became standard in `<jv_to>` (true for pattern matching in switch / record patterns / sealed patterns: preview in 17, standard in 21). If `mvn compile` then fails with `[ERROR] ... is a preview feature and is disabled by default`, the project genuinely needs JDK-`<jv_from>` preview features the bump cannot preserve — bail with `PREVIEW_FEATURES_UNPRESERVABLE`. |
| `org.jsonschema2pojo.exception.ClassAlreadyExistsException` (typically `Could not create enum. [...] Version`) | Stale `target/` from a prior JDK-`<jv_from>` run still contains generated classes. | Cleanup (no pom edit): `docker run --rm --entrypoint bash -v <workdir>:/work j21-fitness:latest -c "rm -rf /work/target"`. Then re-run the failed step. |
| `cannot find symbol [...] class WebSecurityConfigurerAdapter` / `package org.springframework.security.config.annotation.web.configuration does not contain WebSecurityConfigurerAdapter`, OR `incompatible types: org.springframework.http.HttpStatusCode cannot be converted to org.springframework.http.HttpStatus` | Spring Security 6 / Spring Framework 6 breakages that only arise when the app is also being moved to Spring Boot 3: `WebSecurityConfigurerAdapter` was removed, and `ResponseEntity.getStatusCode()` was widened from `HttpStatus` to `HttpStatusCode`. | Run `sb2_to_sb3.sh .` — its `UpgradeSpringBoot_3_3` recipe performs the official Spring Security 6 / Spring Framework 6 migration (`WebSecurityConfigurerAdapter`->`SecurityFilterChain`, `HttpStatus`->`HttpStatusCode`) as part of the Boot 2->3 upgrade. Then `git commit -am "post-bump: sb2->sb3"`, re-run the failed step. |
| Test failure in a `@WebMvcTest` slice: assertion `Status expected:<200> but was:<401>` or `<403>`, AND the project has its own `@Configuration`-annotated `SecurityConfig`/`SecurityConfiguration` class | Spring Boot 3 `@WebMvcTest` slices don't pick up the project's main `SecurityConfig` by default; tests get filter-chain that 401s. | `mvn rewrite:run` with `<RECIPE_FQN>` = `tech.mikhailov.bump_java_version_recipes.AddSecurityConfigImportForWebMvcTest`. Commit + re-run. |
| OAuth2 login test returns `302` redirect to `/login` (or `401`) when the test expected the configured `authenticationEntryPoint`; project uses both `.oauth2Login(...)` and `.exceptionHandling(eh -> eh.authenticationEntryPoint(...))` | Spring Security 6 `.oauth2Login()` registers its own `LoginUrlAuthenticationEntryPoint` that supersedes the global EP. | `mvn rewrite:run` with `<RECIPE_FQN>` = `tech.mikhailov.bump_java_version_recipes.ScopeAuthenticationEntryPointToApiForOAuth2Login`. Commit + re-run. |
| `Java 21 (65) is not supported by the current version of Byte Buddy` (often surfaced by `hibernate-enhance-maven-plugin`, Mockito, or a Spring Boot 2.x app under JDK 21) | A transitively-pinned Byte Buddy (via Hibernate / Mockito / the SB 2.x BOM) predates JDK 21 support (need >= 1.14.9). Usually the *only* JDK-21 blocker and far lighter to fix than a full Spring Boot 3 upgrade. | pom: add to `<dependencyManagement>` `net.bytebuddy:byte-buddy:1.14.12` and `net.bytebuddy:byte-buddy-agent:1.14.12` (a version there overrides the BOM). If the error comes from a plugin (e.g. `hibernate-enhance-maven-plugin`), also add those two as `<dependencies>` of that plugin. Re-run `bump_<jv_from>_to_<jv_to>.sh .`. Only if compile *still* fails on the SB2 BOM, fall through to the Spring Boot 2->3 row below. |
| `ASM ClassReader failed to parse class file - probably due to a new Java class file version that isn't supported yet` AND/OR `Unsupported class file major version 65` | Project's Spring Boot 2.x BOM pins ASM/ByteBuddy/Mockito too old to read JDK 21 bytecode. Needs Spring Boot 2 → 3 upgrade (not currently shipped as a bump script). | Reset the bump (`git reset --hard HEAD`), run `sb2_to_sb3.sh .` (Spring Boot 2 to 3.3; runs under `JDK=<jv_from>`); `git commit -am sb3`; re-run `bump_<jv_from>_to_<jv_to>.sh .`. If compile still fails on residual source the recipe could not auto-migrate, bail `SB2_BOM_NEEDS_SB3_BUMP`. |
| `Could not find a valid Docker environment` / `Previous attempts to find a Docker environment failed` / `Could not start a new session [...] selenium` | Test needs Docker daemon or Selenium server that isn't in the sandbox. Test errored pre-bump too (it's not in `BASELINE_PASS`). | Ignore — these are not regressions. If the only test failures are these, the bump still PASSES the conservation check. If you must bail for other reasons, label `ENV_DOCKER_OR_SELENIUM_UNAVAILABLE`. |

| `javax.validation.ValidationException: Unable to create a Configuration, because no Bean Validation provider could be found. Add a provider like Hibernate Validator` (during `JDK=<jv_to> mvn test`, usually a Spring `LocalValidatorFactoryBean`/`OptionalValidatorFactoryBean` init) | Bean Validation is a Java EE API with no *provider* bundled in JDK 11+; older setups supplied Hibernate Validator transitively and the bump drops it. `Java8toJava11` migrates JAXB/JAX-WS but not the validation provider. | pom: add a provider dependency. javax-era projects (8->11/11->17): `<dependency><groupId>org.hibernate.validator</groupId><artifactId>hibernate-validator</artifactId><version>6.2.5.Final</version></dependency>`; jakarta-era projects (post SB3): use `8.0.1.Final`. Re-run the failed step. |
| `Error injecting: org.codehaus.plexus.archiver.jar.JarArchiver` and/or `ExceptionInInitializerError` at `JarArchiver.<init>` (a Guice/Plexus provisioning error raised by maven-jar/war/assembly during a `JDK=<jv_to>` build) | The project pins an old build plugin whose bundled `plexus-archiver` predates JDK 11 and crashes parsing the runtime Java version; `UpgradePluginsForJava11` did not override the pinned version. | pom: add to `<dependencyManagement>` `org.codehaus.plexus:plexus-archiver:4.2.7` (a version there overrides the plugin's old archiver). If a single plugin still pulls the old one, also pin that plugin (e.g. `maven-jar-plugin` >= 3.4.1). Re-run the failed step. |
| `org.springframework.boot.context.embedded.EmbeddedServletContainerException` or `spring-boot-1.x` / `spring-context-4.x` in the stack trace, with bean-creation/autowire failures under `JDK=<jv_to>` | The project is Spring Boot 1.x / Spring 4.x — its runtime can't start under JDK 11+ until it is on Spring Boot 2.x. | Reset the bump (`git reset --hard HEAD`), run `JDK=<jv_from> sb1_to_sb2.sh .` (Spring Boot 1.x -> 2.7 via OpenRewrite `UpgradeSpringBoot_2_7`); `git commit -am sb2`; re-run `bump_<jv_from>_to_<jv_to>.sh .`. If a higher-hop residual then needs Spring Boot 3 (a `major version 65` / jakarta wall), chain `sb2_to_sb3.sh .`. Only if compile still fails on source the recipe could not migrate, bail `SPRING_BOOT_1X_NEEDS_MANUAL`. |

| `java.lang.ArrayIndexOutOfBoundsException: Index 1 out of bounds for length 1` thrown from a `<clinit>` static initializer (often `...JavaVersion.<clinit>`, e.g. `org.jadira.usertype:usertype.spi`, during Hibernate / `entityManagerFactory` startup under `JDK=<jv_to>`) | An old library parses `System.getProperty("java.version")` expecting the legacy `1.x` shape and reads index `[1]`; the crash needs a **single-token** version (`11` not `11.0.31`). A real JDK 11/17/21 reports a multi-token string and does NOT trigger this — so a single token almost always means the **build is forcing `java.version` to a bare major** via `-Djava.version=<N>` (Maven calls `System.setProperty` for `-D` user properties, so it leaks into the surefire fork and the main JVM alike). | **First check whether the build passes `-Djava.version=<major>`** (build wrapper, CI, surefire `argLine`). If so, remove it — set the compiler level via `-Dmaven.compiler.release`/`source`+`target` only, and let the JVM report its real version (`11.0.x`); that alone clears the crash. A pom-side surefire `systemPropertyVariables` override is unreliable (a command-line `-D` beats it, and bumping only `usertype.core` leaves `usertype.spi` transitive). Re-run the failed step. |
| `Could not find artifact com.sun:tools:jar` or a `<systemPath>.../lib/tools.jar</systemPath>` dependency that no longer resolves under `JDK=<jv_to>` | `tools.jar` was removed in JDK 9+ (the compiler APIs moved into the `jdk.compiler` module); a `com.sun:tools` system-scoped dependency cannot resolve. | pom: delete the `<dependency>` whose `<artifactId>tools</artifactId>` carries `<scope>system</scope>` + the `tools.jar` `<systemPath>`. If the project genuinely calls `com.sun.tools.javac.*` internals (e.g. google-java-format), instead add `--add-exports jdk.compiler/com.sun.tools.javac.<pkg>=ALL-UNNAMED` to `maven-compiler-plugin` `<compilerArgs>` (and the surefire `argLine`). Re-run. |

## When to bail
If after running the bump script + applying every matching fix the build still won't compile or tests still regress vs `BASELINE_PASS`, state which step failed and the unresolved `[ERROR]` (with the bail label if the table prescribes one). Do not invent edits. **When you bail, emit the label on its own line as the final line of your message in the exact form `BAIL:<LABEL>` (uppercase, no backticks, no markdown bold) — e.g. `BAIL:SB2_BOM_NEEDS_SB3_BUMP`.**

## How the bump works (reference — background, not steps to run)

You only ever run `bump_<jv_from>_to_<jv_to>.sh .` (Step 3) and then consult the failure
table. This section explains what that one script does, so none of it is a black box. There
are exactly **two layers of branching**: (1) inside the script — fixed per-hop, the only
variation is which JDK each step uses; (2) across scripts — the failure-table escalations you
apply by hand. The script itself never reads project content and never branches on it.

**Inside `bump_<from>_to_<to>.sh`** — a linear pipeline, every step dispatched through the
`mvn` docker wrapper with `JDK=<n>` chosen per step:

```
1. lombok_safe_bump   JDK=jv_from   Pin Lombok >= 1.18.30 via a temp rewrite.yml
                                     (UpgradeDependencyVersion + ChangePropertyValue for 5
                                     property-name spellings). Old Lombok crashes javac 17/21
                                     (NoSuchFieldError JCTree$JCImport.qualid), so this MUST
                                     run under the OLD JDK before any newer-JDK step.

2. migrate recipes    (public org.openrewrite.recipe:rewrite-migrate-java:3.35.0)
     8->11    Java8toJava11                                              JDK=11
     11->17   UpgradePluginsForJava17 (JDK=11)  ->  UpgradeBuildToJava17 (JDK=17)
     17->21   UpgradePluginsForJava21 (JDK=17)  ->  UpgradeBuildToJava21 (JDK=21)
              ->  transforms21 (JDK=21): 8 source recipes — illegal-semicolons, Thread.stop,
                  URL-ctor->URI.create, SequencedCollection, Locale.of, Runtime.exec,
                  delete-finalize, removed-Subject-methods.

3. compat layer       Deterministic pom/surefire edits, best-effort (a failure here is
                      non-fatal — the script continues):
     8->11    java11_compat.sh   Re-add the EE modules JDK 11 removed (jaxb-api, jaxb-runtime,
                                 javax.activation, javax.annotation-api, jaxws-api) into a real
                                 top-level <dependencies>; if Jadira usertype is present, set
                                 surefire java.version=1.8.0; bump old maven-jar/war/assembly
                                 plugins to JDK-11-aware versions.
     11->17   java17_compat.sh   Inject the --add-opens set into surefire <argLine> (JDK 16+
     17->21                      strong-encapsulation closes reflection old Mockito/ByteBuddy
                                 need); bump old JaCoCo to 0.8.12 (old ASM can't read 17/21).
```

Everything situational lives in the **failure table** above — that is the second branch layer,
and it is the agent's decision, not the script's:

- **Spring Boot 1.x** (runtime won't start on JDK 11+) → reset, `sb1_to_sb2.sh`
  (`UpgradeSpringBoot_2_7`), then re-run the bump.
- **Spring Boot 2 BOM too old for JDK 21** (`major version 65`, ByteBuddy/ASM) → try the
  ByteBuddy `<dependencyManagement>` override first; if it persists → reset, `sb2_to_sb3.sh`
  (`UpgradeSpringBoot_3_3`, which also runs the official Spring Security 6 / javax->jakarta
  migration), then re-run the bump.
- **Everything else** — per-symptom pom edits and the two niche `rewrite:run` security recipes
  — are the individual rows.

So the whole decision tree is: run the linear bump; on a failure, match exactly one row, apply
it, re-run from the failed step; only the two Spring-Boot rows re-route through a second script.

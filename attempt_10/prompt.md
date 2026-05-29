# Dominanta — Java 17 → Java 21 LTS bump

## Purpose
This project builds and passes tests under Java 17. Bump it to Java 21 so the same project builds and the same tests still pass.

## Contract and constraints
Action vocabulary: `git` (init, add, commit, reset --hard, status, diff), `mvn rewrite:run -Drewrite.activeRecipes=<FQN>` (recipes only from the catalog below), `mvn compile`, `mvn test`, and direct edits to `pom.xml` only when a scripted-fix trigger matches verbatim. No other edits. No source changes you author yourself.

**Environment.** Java toolchains and Maven are reachable only through the `mvn` command on your PATH (dispatches to a docker container providing JDK 8/11/17/21 and Maven 3.9). The `java` / `javac` binaries are not directly installed — do not run them directly and do not attempt to install JDK or Maven. `mvn -version` is the toolchain probe. Switch JDK per step with `JDK=<n> mvn …` (e.g. `JDK=21 mvn compile`).

Recipe coordinates on every `mvn rewrite:run`:
```
-Drewrite.recipeArtifactCoordinates=\
org.openrewrite.recipe:rewrite-migrate-java:3.35.0,\
com.claude.recipes:claude-recipes:1.0.0
```
Plugin pin: `org.openrewrite.maven:rewrite-maven-plugin:6.40.0`.

## Search hints — what observed failures have taught

- **git as checkpoint.** Before anything else, `git init && git add -A && git commit -m baseline`, then `JDK=17 mvn test` to record the passing-test set (`BASELINE_PASS`). Every recipe applied later is a candidate commit; if it regresses tests vs `BASELINE_PASS`, `git reset --hard HEAD` and try the next.
- **Three recipes in fixed order.** The chain for 17→21 is short: (1) `upgrade_plugins_for_java21` under JDK 17, (2) `upgrade_build_to_java21` under JDK 21, (3) `java21_transforms` under JDK 21. After each: `mvn compile` then `mvn test`, commit if both pass, otherwise reset.
- **Scripted fixes are direct `pom.xml` edits via your file_editor tool.** They are NOT recipes — do not try to express them via `mvn rewrite:run`. When a build error matches a trigger in the "Scripted fixes" table, open `pom.xml` and make the listed change directly, then re-build.
- **A failed step is informative, not fatal.** When a step regresses or won't compile, `git reset --hard HEAD` and move to the next recipe. The chain converges over multiple steps; do not loop on one step more than twice.

## Reward
`JDK=21 mvn compile` succeeds AND every test in `BASELINE_PASS` passes `JDK=21 mvn test`. The diff vs initial commit is the deliverable.

## Repeat
Cycle through the three recipes under the discipline above until reward is approached. On exhaustion without success, state the last failing recipe + `[ERROR]` block and stop.

---

## Recipe catalog (3 steps, in order)

| # | Label | JDK | Recipe FQN |
|---|---|---|---|
| 1 | upgrade_plugins_for_java21 | 17 | `org.openrewrite.java.migrate.UpgradePluginsForJava21` |
| 2 | upgrade_build_to_java21 | 21 | `org.openrewrite.java.migrate.UpgradeBuildToJava21` |
| 3 | java21_transforms | 21 | comma-separated: `org.openrewrite.java.migrate.RemoveIllegalSemicolons,org.openrewrite.java.migrate.lang.ThreadStopUnsupported,org.openrewrite.java.migrate.net.URLConstructorToURICreate,org.openrewrite.java.migrate.util.SequencedCollection,org.openrewrite.java.migrate.util.UseLocaleOf,org.openrewrite.staticanalysis.ReplaceDeprecatedRuntimeExecMethods,org.openrewrite.java.migrate.DeleteDeprecatedFinalize,org.openrewrite.java.migrate.RemovedSubjectMethods` |

## Custom claude-recipes (invoke as recipes when source pattern matches)

| Source pattern | Recipe FQN |
|---|---|
| `HttpStatus` returned where Spring 6 expects `HttpStatusCode` | `com.claude.recipes.WidenHttpStatusToHttpStatusCode` |

## Scripted fixes (direct pom.xml edits via file_editor; apply ONLY when the trigger string appears in the most recent `[ERROR]` block)

| `[ERROR]` trigger | Exact pom.xml edit |
|---|---|
| `Could not resolve [...] htmlunit:jar:2.6` | Set `net.sourceforge.htmlunit:htmlunit` version to `2.70.0`. |

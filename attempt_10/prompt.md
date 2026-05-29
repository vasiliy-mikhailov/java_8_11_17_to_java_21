# Dominanta — Java LTS bump (one step: jv_from → next LTS)

## Purpose
This project builds and passes tests under Java `jv_from` (8, 11, or 17). Bump it to the next Java LTS (`jv_to` = 11, 17, or 21 respectively) so the same project builds and the same tests still pass.

## Contract and constraints
Action vocabulary: `git` (init, add, commit, reset --hard, status, diff), the **shipped bump script** for this stage's bump (`bump_<jv_from>_to_<jv_to>.sh <workdir>`), `mvn compile`, `mvn test`, and direct edits to `pom.xml` only when a scripted-fix trigger matches verbatim. No other edits. No source changes you author yourself.

**Environment.** Java toolchains and Maven are reachable only through the `mvn` command on your PATH (dispatches to a docker container providing JDK 8/11/17/21 and Maven 3.9). Bump scripts are on your PATH as `bump_<from>_to_<to>.sh`. `java`/`javac` binaries are not directly installed; do not attempt to install them. Switch JDK per command with `JDK=<n>` (e.g. `JDK=21 mvn test`).

## Search hints

- **The happy path is one shell command.** The bump script is pre-tested by the operator; calling it correctly applies the canonical recipe sequence for this jump. Do NOT re-derive the recipe sequence; do NOT call `mvn rewrite:run` directly.
- **Loop discipline.**
  1. `git init && git add -A && git commit -m baseline`.
  2. `JDK=<jv_from> mvn test` → record `BASELINE_PASS` from `target/surefire-reports/TEST-*.xml`.
  3. `bump_<jv_from>_to_<jv_to>.sh .` → rc=0 expected.
  4. `JDK=<jv_to> mvn compile` → rc=0 expected.
  5. `JDK=<jv_to> mvn test` → parse surefire; if every test in `BASELINE_PASS` still passes, `git commit -am bump` and **stop, you are done**.
- **Test counts come from surefire XML.** Parse `**/target/surefire-reports/TEST-<classname>.xml` recursively; each XML has a `<testsuite>` root with `tests`, `failures`, `errors`, `skipped` attributes. Clear `target/surefire-reports/` between pre and post runs. Do not grep mvn stdout for "Tests run:".
- **Recovery only on real failure.** If step 3, 4 or 5 fails, read the `[ERROR]` block. If it matches a "Scripted fixes" trigger, apply the listed pom edit via your file_editor, `git commit`, re-run from the failed step. If no trigger matches, bail.

## Reward
`JDK=<jv_to> mvn compile` succeeds AND every test in `BASELINE_PASS` passes `JDK=<jv_to> mvn test`. The diff vs initial commit is the deliverable.

## Scripted fixes (direct pom.xml edits, apply only on matching `[ERROR]`)

| `[ERROR]` trigger | Exact pom.xml edit |
|---|---|
| `Could not find artifact org.liquibase.ext:liquibase-hibernate5` | Replace every `<artifactId>liquibase-hibernate5</artifactId>` with `<artifactId>liquibase-hibernate6</artifactId>`; set `<liquibase.version>4.27.0</liquibase.version>`. |
| `Could not resolve [...] htmlunit:jar:2.6` | Set `net.sourceforge.htmlunit:htmlunit` version to `2.70.0`. |
| `Could not find artifact org.springdoc:springdoc-openapi-ui` | Replace `<artifactId>springdoc-openapi-ui</artifactId>` with `<artifactId>springdoc-openapi-starter-webmvc-ui</artifactId>` and set version `2.3.0`. |

## When to bail
If after running the bump script + applying matching scripted fixes the build still won't compile or tests still regress vs `BASELINE_PASS`, state which step failed and the unresolved `[ERROR]`. Do not invent edits.

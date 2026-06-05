# Recipe catalog — bump-java-version

The failure-remedy table in `SKILL.md` calls custom OpenRewrite recipes by FQN. They ship as
one Maven artifact (a dependency, not bundled source):

**Coordinate:** `io.github.vasiliy-mikhailov:bump-java-version-recipes:1.0.0`

**Recipe FQNs** (used as `-Drewrite.activeRecipes=…`):
- `tech.mikhailov.bump_java_version_recipes.AddSecurityConfigImportForWebMvcTest`
- `tech.mikhailov.bump_java_version_recipes.ScopeAuthenticationEntryPointToApiForOAuth2Login`

**`rewrite:run` template** (substitute `<RECIPE_FQN>`):

```
JDK=<jv_to> mvn -B -ntp org.openrewrite.maven:rewrite-maven-plugin:6.40.0:run \
  -Drewrite.activeRecipes=<RECIPE_FQN> \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-migrate-java:3.35.0,io.github.vasiliy-mikhailov:bump-java-version-recipes:1.0.0
```

**Building the catalog:** the source is the `recipes/` Maven module at `current_attempt/recipes/`.
Install it into the local Maven cache the bump scripts read from:

```
cd current_attempt/recipes && JDK=17 mvn -q -B -ntp clean install
```

It is published to Maven Central as `io.github.vasiliy-mikhailov:bump-java-version-recipes:1.0.0`;
the bump scripts and `mvn` wrapper resolve it from the local `.m2` cache (warmed from Central),
so no manual build+install is required.

# Environment the scripts assume

- `mvn` on PATH dispatches Maven inside a container providing JDK 8/11/17/21 + Maven 3.9; pick
  the JDK per command with `JDK=<n>` (e.g. `JDK=21 mvn test`). The container runs as the
  invoking uid (non-root), so build outputs are owned by the caller.
- `scripts/bump_<from>_to_<to>.sh` must be on PATH (or invoked by path); each runs the
  OpenRewrite cascade for that one LTS step (lombok-safe bump → plugins → build → transforms).
- `scripts/sb2_to_sb3.sh` upgrades Spring Boot 2 → 3.3 for the SB2-BOM / `major version 65`
  cohort, before the Java bump.
- `scripts/sb1_to_sb2.sh` upgrades Spring Boot 1.x to 2.7 (OpenRewrite `UpgradeSpringBoot_2_7` from rewrite-spring) for very old apps whose runtime won't start under JDK 11+, before the Java bump.

# How OpenHands consumes this skill

`SKILL.md`'s frontmatter (name + description) is what the agent matches on; the body is the
six-section migration procedure. To use it on a target repo, either place this skill directory
under the workspace's `.agents/skills/` (OpenHands auto-discovers + progressively discloses it),
or feed `SKILL.md`'s body as the task prompt (the current `oh_one.py` path), with `scripts/` on
PATH and the recipe artifact installed in the local `.m2` cache.

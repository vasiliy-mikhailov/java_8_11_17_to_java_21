# attempt_2 iter-12 — spotbugs Groovy/Java-21 incompat: parent-pom-controlled, declarative primitives can't reach

## Mutation
Added `addVersionIfMissing: true` to the existing `UpgradePluginVersion: com.github.spotbugs:spotbugs-maven-plugin → 4.8.x` directive.

## Result on 2 targeted repos (both = `easybinder` project)
Both still fail with `Failed to execute goal com.github.spotbugs:spotbugs-maven-plugin:3.1.11:spotbugs` — `Could not initialize class org.codehaus.groovy.vmplugin.v7.Java7` (Groovy 2 + Java 21 incompat, fails at plugin class loading before `<skip>` is read).

| repo | build_post |
|------|:---:|
| `hibernate-5__j11__3` | 0 |
| `jakarta-ee-javax__j11__2` | 0 |

## Root cause analysis
The pom diff shows **no spotbugs change** — `UpgradePluginVersion` did not fire even with `addVersionIfMissing: true`. The reason: spotbugs-maven-plugin is pulled in from the project's parent pom's `<pluginManagement>`, never declared in this child pom. `UpgradePluginVersion` can only modify versions where the plugin is *declared* (build/plugins or build/pluginManagement). It won't synthesize a brand-new `<plugin>` entry in a child pom that has no `<plugins>` section for that plugin.

## Why this lands in bespoke territory
Three remaining declarative paths exhausted:
1. `UpgradePluginVersion` — no-op, plugin not in this pom
2. `-Dspotbugs.skip=true` — already in MVN_OPTS_COMPAT, plugin fails at class loading before `<skip>` is read
3. `UpgradeParentVersion` — could in principle bump the parent to a version where spotbugs >= 4.7.x, but parent project versions are repo-private (no published 4.7-spotbugs version of this parent)

Real fixes outside declarative-delta scope:
- Synthesize a `<pluginManagement>` override block in the child pom (would need a custom recipe or `AddPluginExecution`)
- Modify the runner's `mvn` invocation to bypass the spotbugs goal binding entirely (`mvn ... -P!spotbugs`-style hack, needs per-repo profile knowledge)
- Patch the j21-fitness image with a Groovy 3 jar override for Maven plugins (env-level workaround)

## Per #7 Repeat clause
"Stop when only bespoke engineering remains." This cluster is bespoke. Move on.

## Champion stays iter-9 (54/96, 56%)

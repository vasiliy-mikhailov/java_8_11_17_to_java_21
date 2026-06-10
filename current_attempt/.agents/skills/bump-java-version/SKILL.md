---
name: bump-java-version
description: Migrate a Maven or Gradle project from one Java LTS to the next (8->11, 11->17, 17->21, 21->25) so it still compiles under the new JDK and previously-passing tests still pass — by hand, using only standard tools (JDKs, Maven or Gradle, and OpenRewrite recipes from Maven Central; no project-specific scripts). Use when upgrading or bumping the Java version of a Maven or Gradle project, modernizing to a newer JDK or LTS, or performing the Spring Boot 1->2 / 2->3 and javax->jakarta migration that a Java upgrade requires.
---

# Bumping a Maven or Gradle project one Java LTS step — by hand

Migrate a Maven project **one** Java LTS step (8→11, 11→17, 17→21, or 21→25) so it **compiles** under the
new JDK and every test that **passed before still passes**. Uses only standard tools — **JDKs,
Maven, and OpenRewrite** (recipes pulled from Maven Central). No project-specific scripts. **If the
project is Gradle** (`build.gradle`/`.kts` + `gradlew`, no `pom.xml`), follow **section G** at the end
instead of the Maven steps §1–§7.

---

## 0. Tools you need (all standard)

- The **two JDKs** — the one the project builds with now (`jv_from`) and the target (`jv_to`).
  e.g. for 8→11 you need JDK 8 **and** JDK 11. Select per command with `JAVA_HOME`.
- **Maven** (`mvn`, or the project's `./mvnw`).
- **Internet** — OpenRewrite recipes and any new deps come from Maven Central.
- **git** — commit a baseline first so you can `diff`/revert.

Do **one** step at a time (8→17 = do 8→11 fully green, then 11→17).

Versions used below are known-good; newer point releases are fine:
- rewrite-maven-plugin `6.40.0`, `rewrite-migrate-java` `3.35.0`, `rewrite-spring` `6.31.0`.
- For the **21→25** hop use `rewrite-maven-plugin` `6.41.0` + `rewrite-migrate-java` `3.36.0` — these carry the Java-25 recipes (`UpgradeBuildToJava25`, `UpgradePluginsForJava25`).

---

## 1. Record the baseline (OLD JDK)

```bash
git add -A && git commit -m baseline
JAVA_HOME=<jdk_from> mvn -B -ntp test
```
Read every `**/target/surefire-reports/TEST-*.xml`; the tests with **0 failures/errors** are your
**baseline-pass set** — the contract to conserve. Tests already failing in the baseline (no Docker,
no DB, no network) are **not** your responsibility.

---

## 2. Make Lombok safe (if the project uses Lombok)

Lombok **< 1.18.30** crashes `javac` 17/21 (`NoSuchFieldError: JCTree$JCImport.qualid`); and Lombok
**< 1.18.40** crashes `javac` **25** (`ExceptionInInitializerError: com.sun.tools.javac.code.TypeTag ::
UNKNOWN`). Edit the pom: set the Lombok version (or the `lombok.version` property) to **1.18.30+** for
JDK 17/21, **1.18.40+** for JDK 25 (a project already on 1.18.3x still needs the bump for 25). Do this
**before** any step under the new JDK.

---

## 3. Run the OpenRewrite migration

These are the **official** OpenRewrite "migrate to Java N" recipes from
`org.openrewrite.recipe:rewrite-migrate-java`. Invoke the plugin directly (no pom changes needed):

**8 → 11** — one recipe:
```bash
JAVA_HOME=<jdk_to> mvn -B -ntp -U -Denforcer.skip=true \
  org.openrewrite.maven:rewrite-maven-plugin:6.40.0:run \
  -Drewrite.activeRecipes=org.openrewrite.java.migrate.Java8toJava11 \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-migrate-java:3.35.0
```

**11 → 17** — run these **in order** (same command shape, swap the recipe):
1. `org.openrewrite.java.migrate.UpgradePluginsForJava17`
2. `org.openrewrite.java.migrate.UpgradeBuildToJava17`

**17 → 21** — in order:
1. `org.openrewrite.java.migrate.UpgradePluginsForJava21`
2. `org.openrewrite.java.migrate.UpgradeBuildToJava21`

**21 → 25** — in order. This hop needs the newer artifacts (`rewrite-maven-plugin:6.41.0` +
`rewrite-migrate-java:3.36.0`), which ship the Java-25 recipes; run with **JDK 25** as `<jdk_to>`:
1. `org.openrewrite.java.migrate.UpgradePluginsForJava25`
2. `org.openrewrite.java.migrate.UpgradeBuildToJava25`

```bash
JAVA_HOME=<jdk_to> mvn -B -ntp -U -Denforcer.skip=true \
  org.openrewrite.maven:rewrite-maven-plugin:6.41.0:run \
  -Drewrite.activeRecipes=org.openrewrite.java.migrate.UpgradeBuildToJava25 \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-migrate-java:3.36.0
```

> **If the OpenRewrite step itself fails to compile** (it type-attributes by compiling, e.g.
> `package javax.xml.bind does not exist`): either apply the **EE-deps fix from §4 first**, or run
> the recipe under the **OLD** JDK (`JAVA_HOME=<jdk_from>`), where the project still compiles — then
> continue. (Projects with `<annotationProcessorPaths>` — MapStruct/JHipster — see Troubleshooting.)

Review the diff (`git diff`) before continuing; commit it.

---

## 4. Apply the deterministic JDK-removal fixes (plain pom edits)

The migration recipe doesn't cover everything the JDK removed. Apply these **proactively** for the
relevant hop (symptoms/extra cases in Troubleshooting):

**For 8→11 (and 11→17 if still javax-era)** — re-add the Java-EE modules removed in JDK 11, into a
real top-level `<dependencies>`:
```xml
<dependency><groupId>javax.xml.bind</groupId><artifactId>jaxb-api</artifactId><version>2.3.1</version></dependency>
<dependency><groupId>org.glassfish.jaxb</groupId><artifactId>jaxb-runtime</artifactId><version>2.3.1</version><scope>runtime</scope></dependency>
<dependency><groupId>com.sun.activation</groupId><artifactId>javax.activation</artifactId><version>1.2.0</version><scope>runtime</scope></dependency>
<dependency><groupId>javax.annotation</groupId><artifactId>javax.annotation-api</artifactId><version>1.3.2</version></dependency>
<dependency><groupId>javax.xml.ws</groupId><artifactId>jaxws-api</artifactId><version>2.3.1</version></dependency>
```
And if the effective `maven-surefire-plugin` is **≤ 2.21** (old Spring Boot parents pin it), floor it:
set `<maven-surefire-plugin.version>2.22.2</maven-surefire-plugin.version>` in `<properties>` — it
NPEs under JDK 9+ otherwise.

**For 11→17, 17→21, and 21→25** — the test fork needs strong-encapsulation opened. Add to the
`maven-surefire-plugin` `<configuration>` an `<argLine>` with:
```
--add-opens java.base/java.lang=ALL-UNNAMED --add-opens java.base/java.lang.reflect=ALL-UNNAMED
--add-opens java.base/java.util=ALL-UNNAMED --add-opens java.base/java.text=ALL-UNNAMED
--add-opens java.base/java.io=ALL-UNNAMED --add-opens java.base/java.nio=ALL-UNNAMED
--add-opens java.base/java.time=ALL-UNNAMED --add-opens java.base/sun.nio.ch=ALL-UNNAMED
--add-opens java.desktop/java.awt.font=ALL-UNNAMED --add-opens java.management/java.lang.management=ALL-UNNAMED
```
(preserve any existing `<argLine>`, e.g. JaCoCo's `@{argLine}`). And if JaCoCo is pinned at an old
version, bump `jacoco-maven-plugin` to **0.8.12** (JDK 17/21) — or **0.8.13+** for JDK 25; older ASM can't read class-file major 61/65/69.

---

## 5. Compile + test under the NEW JDK, conserve

```bash
JAVA_HOME=<jdk_to> mvn -B -ntp -DskipTests compile      # must succeed
JAVA_HOME=<jdk_to> mvn -B -ntp test                     # baseline-pass set must still pass
```
On any failure: find the first real `[ERROR]`, apply the matching fix below, `git commit`, re-run the
**failed** step. **Done when** it compiles under `jv_to` AND baseline-pass ⊆ post-pass.

---

## 6. Spring Boot upgrades (only when the failure points there)

These are full upgrades — do them only if Troubleshooting sends you here, then re-run §3–§5. Same
command shape as §3, recipe artifact `org.openrewrite.recipe:rewrite-spring:6.31.0` — **keep this on
the plugin's rewrite line** (6.x for `rewrite-maven-plugin:6.40.0`); a stale `rewrite-spring` (5.x/7.x)
fails with a cryptic `ReplaceStringLiteralValue … is required` NPE (see §7):

**Spring Boot 1.x → 2.7** (1.x can't run on JDK 11) — run under the OLD JDK:
```bash
JAVA_HOME=<jdk_from> mvn -B -ntp -U -Denforcer.skip=true \
  org.openrewrite.maven:rewrite-maven-plugin:6.40.0:run \
  -Drewrite.activeRecipes=org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7 \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:6.31.0
```

**Spring Boot 2.x → 3.3** (SB2 BOM too old for JDK 21 / ASM, or Spring Security 6 needed):
same command with `-Drewrite.activeRecipes=org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_3`.
This also performs the javax→jakarta and Spring Security 6 migrations.

---

## 7. Troubleshooting (match the first real `[ERROR]`)

| Symptom | Cause | Fix |
|---|---|---|
| `package javax.xml.bind… does not exist`, `XmlTransient`, `JAXBException`, `javax/annotation/Generated` | EE modules removed in JDK 11 | The §4 EE deps. **If during annotation processing** (`<annotationProcessorPaths>` present): regular deps aren't on the processor path — add `jaxb-api` + `javax.annotation-api` as `<path>` entries inside `<annotationProcessorPaths>` too. |
| `maven-surefire-plugin:2.20/2.21 … NullPointerException` | surefire ≤ 2.21 broken on JDK 9+ | Force surefire **2.22.2+** (pom version, or `<maven-surefire-plugin.version>2.22.2</…>` if BOM-pinned). |
| `Cannot define class using reflection` / `sun.misc.Unsafe.defineClass` / `MockitoException` (often then `OutOfMemoryError`) | old Mockito's shaded ByteBuddy uses removed `sun.misc.Unsafe` | Bump **Mockito** (not byte-buddy — it's shaded). Add **before** any BOM import in `<dependencyManagement>`: `org.mockito:mockito-core:2.23.4` + `org.objenesis:objenesis:3.2`. (Match the newest patch if the tests use the Mockito 3/4/5 API.) |
| `ASM ClassReader failed to parse` / `Unsupported class file major version 61/65/69` | ByteBuddy/ASM too old for JDK 17/21/25 | Light: dM `net.bytebuddy:byte-buddy(:agent):1.14.12` (JDK 17/21; use the newest 2025+ release for JDK 25). If it's Spring's component-scan ASM (Spring 5.2.x / SB 2.0–2.1): do the **SB 2→3** upgrade (§6) instead. |
| `WARNING: … sun.misc.Unsafe::objectFieldOffset`/`arrayBaseOffset … terminally deprecated` from a dependency (jctools, Netty, …) on JDK 25+ — or an outright failure once a JDK removes it | the dep is built on `sun.misc.Unsafe` (deprecated-for-removal since JDK 23) | **A newer version often does NOT fix it** — jctools 4.0.5 still calls it; verify the *proposed* version on the target JDK before shipping. Prefer an Unsafe-free code path the lib already ships: e.g. jctools `org.jctools.queues.atomic.*` (AtomicFieldUpdater-backed) in place of `org.jctools.queues.*`. If it's only a **warning** and tests still pass, it's cosmetic — conserve, don't force it. |
| `ArrayIndexOutOfBoundsException: Index 1 out of bounds for length 1` from a `<clinit>` (Jadira; Hibernate Validator 5.x → "Failed to load ApplicationContext") | old lib parses `java.version`/`java.specification.version` as legacy `1.x` | Don't pass `-Djava.version=<major>` (let the JVM report its real version). If it's Hibernate Validator 5.x, bump it (`hibernate-validator` 6.2.5.Final). |
| `ExceptionInInitializerError: com.sun.tools.javac.code.TypeTag :: UNKNOWN` during compile/testCompile | Lombok too old for the new JDK (esp. **JDK 25**) — a different symptom from the `JCImport.qualid` one, same root cause | Bump `lombok.version`: **1.18.30+** for 17/21, **1.18.40+** for 25. Applies even if the project is already on a 1.18.3x release. |
| `Error injecting JarArchiver` / `ExceptionInInitializerError at JarArchiver.<init>` | old `maven-jar/war/assembly` plexus-archiver predates JDK 11 | Bump the plugin (`maven-jar-plugin ≥ 3.4.1`) or dM `org.codehaus.plexus:plexus-archiver:4.2.7`. |
| `com.sun:tools:jar` not found / `tools.jar` systemPath | `tools.jar` removed in JDK 9 | Delete the `com.sun:tools` system-scoped dependency. If code uses `com.sun.tools.javac.*`: add `--add-exports jdk.compiler/com.sun.tools.javac.*=ALL-UNNAMED` to `maven-compiler-plugin` `<compilerArgs>` **and** surefire `<argLine>`, and use `<source>/<target>` (NOT `<release>`). |
| `no Bean Validation provider could be found` | provider dropped | Add `org.hibernate.validator:hibernate-validator` (6.2.5.Final javax / 8.0.1.Final jakarta). |
| `OutOfMemoryError` during tests (JHipster etc.) | **usually downstream** of a context-load failure | Fix the **first** real error first; only raise the surefire `-Xmx` if it's genuinely heap. |
| `EmbeddedServletContainerException` / `spring-context-4.x`, bean-creation failures | Spring Boot 1.x can't run on JDK 11 | Do the **SB 1→2** upgrade (§6), then re-run. *(Apps with custom SB-1.x code on SB-2-removed APIs — e.g. WebGoat — won't compile on SB2; bail.)* |
| `cannot find symbol: class WebSecurityConfigurerAdapter` | Spring Security 6 (only after going to SB3) | Do the **SB 2→3** upgrade (§6), which migrates it. |
| `Recipe validation error … ReplaceStringLiteralValue … is required` / `NullPointerException` during `rewrite:run` (esp. an `UpgradeSpringBoot_3_x`) | `rewrite-spring` version is off the plugin's rewrite line (e.g. rewrite-7.x `rewrite-spring:5.x` against `rewrite-maven-plugin:6.40.0` = rewrite-8.x) | Use a coherent set: `rewrite-spring:6.31.0` with the 6.40.0 plugin. If you also pin `rewrite-migrate-java`, keep both from one `rewrite-recipe-bom` (e.g. `rewrite-spring:6.29.0` + `rewrite-migrate-java:3.32.0`). |
| `jsonschema2pojo … ClassAlreadyExistsException` | stale generated classes in `target/` | `rm -rf target` (or `mvn clean`), re-run. |
| Docker/Selenium/DB test errors (`Could not find a valid Docker environment`, Testcontainers, MariaDB4j) | needs infra the box lacks — failed in baseline too | Ignore — not a regression. |
| no `pom.xml` at root | nested project | `find . -name pom.xml -not -path '*/target/*'`, `cd` into the shallowest, run steps there. |

---

## 8. When to bail (honestly)

After the migration + every matching fix, if it still won't compile or tests still regress, stop and
report the failed step + the unresolved `[ERROR]`. Known genuine bails:
- **Spring Boot 1.x app whose custom code calls SB-2-removed APIs** (`EmbeddedServletContainerFactory`,
  `actuate.endpoint.mvc`, `thymeleaf.resourceresolver`) — needs a hand-written migration.
- **JHipster-8 app whose OpenRewrite step fails with a cascade** (JAXB → `javax.annotation.Generated`
  → MapStruct/jpamodelgen NPE) — the annotation-processing stack is too old for JDK 11; the real fix
  is a JHipster/Spring-Boot version upgrade, beyond a one-LTS-step bump.
- **Source genuinely uses a removed JDK API** that no recipe can rewrite.

An honest bail with the reason beats a green build that hides a dropped test.


---

## G. Gradle projects (`build.gradle` / `build.gradle.kts`) — use *instead of* §1–§7

Same goal — compile under `jv_to` and conserve every previously-passing test — with Gradle tools.
Detect: a `build.gradle`/`.kts` + `gradlew` at the root and **no `pom.xml`**.

1. **Baseline:** `JAVA_HOME=<jdk_from> ./gradlew test`. Read `build/test-results/test/TEST-*.xml`; the
   0-failure tests are your conserve set. Always use the repo's `./gradlew`, never a system `gradle`. The declared toolchain/`languageVersion` is the *bytecode target*, **not** necessarily the JDK the build runs on — a codegen tool (e.g. ANTLR) can demand a higher JDK than the toolchain says (a project declaring `of(8)` may actually need JDK 11+ to build). Trust what compiles, not the number; that real floor is your true `jv_from`.
2. **Set the Java version to `jv_to`** in the build script: the toolchain
   `java { toolchain { languageVersion = JavaLanguageVersion.of(<jv_to>) } }`, or
   `sourceCompatibility`/`targetCompatibility`/`options.release`, or for Kotlin `kotlin { jvmToolchain(<jv_to>) }`.
   Often this single change is the whole bump (verified: a Spring Boot 2.7 / Gradle 8.10 project went
   11→17 with only the toolchain edit).
3. **Bump the Gradle wrapper if it predates `jv_to` — the #1 Gradle wall:** JDK 17 needs Gradle ≥ 7.3,
   JDK 21 ≥ 8.5, JDK 25 ≥ 9.0 — Gradle 8.x can't even *run* a JDK-25 toolchain (it fails parsing the version string), so ≥ 9.0 is required to build/test **on** 25, not just to emit 25 bytecode. `./gradlew wrapper --gradle-version <X>` (run it under the OLD JDK if the
   current wrapper won't even start on `jv_to`).
4. **Lombok:** same floors as §2 (Maven) — set the Lombok dependency / `lombok.version` to **1.18.30+**
   for 17/21, **1.18.40+** for 25.
5. **If step 2 still doesn't compile, run the SAME OpenRewrite recipes via the `rewrite-gradle-plugin`
   init-script** (no build edits; verified end-to-end):
   ```bash
   cat > /tmp/rw.init.gradle <<'G2'
   initscript {
     repositories { gradlePluginPortal(); mavenCentral() }
     dependencies { classpath("org.openrewrite:plugin:latest.release") }
   }
   rootProject {
     apply plugin: org.openrewrite.gradle.RewritePlugin
     dependencies { rewrite("org.openrewrite.recipe:rewrite-migrate-java:latest.release") }
     rewrite { activeRecipe("org.openrewrite.java.migrate.UpgradeToJava17") }   // or UpgradeBuildToJava21 / UpgradeBuildToJava25
   }
   G2
   JAVA_HOME=<jdk_to> ./gradlew --no-daemon --init-script /tmp/rw.init.gradle rewriteRun
   ```
6. **Conserve:** `JAVA_HOME=<jdk_to> ./gradlew test` — the conserve set ⊆ post-pass.

The Spring Boot upgrades (§6) and the Troubleshooting table (§7) apply the same; Gradle equivalents:
extra deps go in `dependencies {}`, and test-JVM `--add-opens` go in `tasks.test { jvmArgs("--add-opens=...") }`.

**Kotlin coexistence:** if the project also has Kotlin (`compileKotlin` task / `kotlin {}` plugin), set the **Kotlin** JVM target too — `kotlin { jvmToolchain(<jv_to>) }`, not just the Java toolchain — or Gradle fails with *"Inconsistent JVM-target compatibility detected for tasks 'compileJava' (N) and 'compileKotlin' (M)"*. JVM target **25 needs Kotlin ≥ 2.2** (older Kotlin caps at JVM 21/22); in **Quarkus** the Kotlin version is pinned by the platform BOM, so bump the **Quarkus platform**, not Kotlin directly (a raw Kotlin bump is overridden).

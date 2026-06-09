# Dataset discovery (P4) — find FRESH unique repos by Java version + build tool

Durable record of the repo-discovery harness so it survives across sessions. This is **P4 harness
tooling**, deliberately NOT in the consumer-facing `bump-java-version` SKILL.md (that skill is
scriptless and harness-agnostic). Discovery feeds `sample_shas.py`, which validates which candidates
actually compile into baselines.

## What it does
GitHub **code-search** (via the `gh` CLI — sanctioned GitHub path, not raw curl) for repos that
*declare* a given Java version, deduped against everything we already have, emitting fresh candidate
repo-lists. Candidates are not yet baselines — `sample_shas.py` clones each and checks it compiles.

## Scripts (here, versioned)
- `discover_maven.py` — Maven repos. Searches `filename:pom.xml` for `<java.version>N<`,
  `<maven.compiler.source|target|release>N<`. (currently hardcoded jv set 17,21 — edit `Q`/`JVS` to retarget.)
- `discover_gradle.py JVLIST` — Gradle repos. Searches `filename:build.gradle` **and**
  `filename:build.gradle.kts` for `JavaLanguageVersion.of(N)` (toolchain DSL, both Groovy/Kotlin) and
  `JavaVersion.VERSION_N` (source/targetCompatibility). e.g. `discover_gradle.py 17,21`.

Run (token via gh):
```bash
cd /home/vmihaylov/java_8_11_17_to_java_21
GITHUB_TOKEN=$(gh auth token) python3 current_attempt/tools/discover_maven.py
GITHUB_TOKEN=$(gh auth token) python3 current_attempt/tools/discover_gradle.py 17,21
```

## Dedup ("known" set, ~10.5k repos)
Both scripts build the known set from: `dataset-repos.json` + `dataset-shas.json` (iter-db) +
`corpus/attempt_db.json` (baselines + repo_pool_by_jv + trajectories) + every `~/*dig*.json` +
existing `/tmp/j17*.txt|j21*.txt|gradle_*.txt`. Only repos NOT in that set are written out.

## Rate limit (IMPORTANT)
GitHub **search API = 30 req/min** (global per token). Scripts sleep 2.2s between pages and 60s on a
429. **Run Maven and Gradle digs SEQUENTIALLY, never concurrently** — they share the one limit and
will starve each other. The chain pattern used: a waiter polls `pgrep -f discover_maven` then starts
the Gradle one.

## Candidate counts found this session (deduped, FRESH new-unique)
| Build tool | J17 | J21 |
|---|---|---|
| Maven  | 3431 | 3293 |
| Gradle | ~2900 | ~2200+ (J21 run in progress when recorded) |

Lists live in `current_attempt/corpus/discovered/{maven,gradle}_j{17,21}_fresh.txt`.

## HOW TO RESUME (validate candidates → baselines)
**Maven** (works today): run `sample_shas.py` on a fresh list to keep only repos that test-compile,
appending validated `{repo,sha,jv_from}` baselines:
```bash
python3 current_attempt/tools/sample_shas.py --only-from=17 --seed=0 --max-attempts=5 --scan-cap=70 \
  --repos-file=current_attempt/corpus/discovered/maven_j17_fresh.txt --out=/home/vmihaylov/j17dig2.json
```
Then fold validated baselines into `corpus/attempt_db.json` and draw the next iter-db from it.

**Gradle** (NOT built yet — pending work): `sample_shas.py` is Maven-only (`pom.xml` + `mvn
test-compile`). Gradle needs: detect `build.gradle`/`.kts`, parse jv, validate via `./gradlew
testClasses` under a JDK whose **Gradle-wrapper version supports it** (JDK 21 → Gradle 8.5+, JDK 17 →
7.3+). Then the bump path (OpenRewrite via `rewrite-gradle-plugin` init-script + `gradle rewriteRun`,
conserve via `gradle test`) and a Gradle track in SKILL.md. Build + TEST against a real
`gradle_j17_fresh.txt` repo before trusting any of it (verify-don't-guess).

## Contract
AGENTS.md P4 now admits Gradle (declares jv via `pom.xml` OR `build.gradle`/`.kts`; validate via
`mvn test-compile` OR `gradle testClasses`). P2/P3 admit a Maven-or-Gradle deliverable.

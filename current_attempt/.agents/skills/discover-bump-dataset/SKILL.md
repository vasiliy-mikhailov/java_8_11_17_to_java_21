---
name: discover-bump-dataset
description: Discover and expand the training dataset of real GitHub repos used to evaluate and harden the bump-java-version skill. Find FRESH unique Maven or Gradle projects that declare a given Java LTS (8/11/17/21), dedupe them against the corpus we already have, and validate which actually compile into baselines. Use when growing the corpus, filling a Java-version gap (e.g. need more J17/J21 baselines), or adding a build tool (Gradle). Harness tooling — NOT the portable bump-java-version skill.
---

# Discover the bump-java-version training dataset — by hand

Find real GitHub repos that **declare** a target Java version, dedupe against everything we already
have, and **validate** which ones actually compile into baselines — to grow the corpus the
`bump-java-version` skill is scored against (P4). Uses only standard tools: the **`gh` CLI**, **git**,
**jq**, and the project's build tool (**Maven**/**Gradle**). No project-specific scripts — you run the
searches and checks yourself so the method can't rot.

Repo root: `/home/vmihaylov/java_8_11_17_to_java_21`; the open attempt is `current_attempt/`.

> **Distribution: internal only.** This skill lives solely in the `bump_java_version` research repo.
> It is **never** published to the public `bump-java-version-skill` repo — P11 ships only the portable
> `bump-java-version` SKILL.md (verbatim) plus packaging. Do not sync this skill across.

Two build tools, two surfaces: **Maven** = `pom.xml`; **Gradle** = `build.gradle` / `build.gradle.kts`.
A candidate only *declares* a version — it is not a baseline until §3 proves it compiles.

---

## 0. Tools

- **`gh`**, authenticated (`gh auth status`). All GitHub access goes through `gh api` — the sanctioned
  path. Never scrape with raw `curl`/`urllib`.
- **`git`**, **`jq`**, **`python3`** (for small inline filters only).
- The **two JDKs** + **Maven**/**Gradle** for the compile check, same as the bump skill.

---

## 1. Build the "known" set (what to dedupe against)

Collect every repo we already have into one sorted file, so discovery only surfaces genuinely new
repos. Pull names from each corpus source (adapt the `jq` paths if a file's shape differs — verify
with `jq 'keys'` first):

```bash
cd /home/vmihaylov/java_8_11_17_to_java_21
{
  jq -r '.[]'                         current_attempt/dataset-repos.json
  jq -r '.[].repo'                    current_attempt/dataset-shas.json
  jq -r '.baselines[]      | keys[]'  current_attempt/corpus/attempt_db.json
  jq -r '.repo_pool_by_jv[]| keys[]'  current_attempt/corpus/attempt_db.json
  jq -r '.trajectories[].repo'        current_attempt/corpus/attempt_db.json
  for f in /home/vmihaylov/*dig*.json; do jq -r '(.[]?|.repo // .) // empty' "$f"; done
  cat current_attempt/corpus/discovered/*.txt 2>/dev/null
} | sed 's/@.*//' | grep '/' | sort -u > /tmp/known.txt
wc -l /tmp/known.txt          # expect ~10k+
```

---

## 2. Search GitHub code for fresh candidates

For the target version **N** and build tool, run each query below, paginate, and collect repo names.
**Anchor the value** so code-search tokenizes it; drop `language:Java` (it zeroes out combined with the
angle-bracket phrase).

**Maven** (`filename:pom.xml`):
`"<java.version>N<"`, `"<maven.compiler.source>N<"`, `"<maven.compiler.target>N<"`, `"<maven.compiler.release>N<"`

**Gradle** — run for **both** filenames (`.kts` is a distinct filename):
`filename:build.gradle` and `filename:build.gradle.kts`, each with `"JavaLanguageVersion.of(N)"`
(toolchain DSL, Groovy+Kotlin) and `"JavaVersion.VERSION_N"` (source/targetCompatibility). **Java 8 is special in Gradle:** it is `JavaVersion.VERSION_1_8` and `sourceCompatibility = '1.8'` (not `_8`) — search those for J8.

Run one query, paging until a page returns < 100:

```bash
Q='filename:pom.xml "<maven.compiler.release>17<"'        # one example query
for p in $(seq 1 10); do
  gh api -X GET search/code -f q="$Q" -f per_page=100 -f page=$p \
    --jq '.items[].repository.full_name' >> /tmp/hits.txt || { sleep 60; continue; }
  sleep 3                                                  # < 30/min (see rate limit below)
done
```

**Rate limit — the one hard rule:** the GitHub **search API is 30 requests/min** per token. Sleep
~2–3s between calls; on a 429 sleep 60 and retry. **Never run two searches in parallel** (Maven and
Gradle, or two versions) — they share the one limit and starve each other. A full Maven+Gradle sweep
for one version is ~12 query-sets × a few pages — minutes, not seconds.

Dedupe the hits to fresh-only and persist out of `/tmp` (it's ephemeral):

```bash
sort -u /tmp/hits.txt | grep -vxF -f /tmp/known.txt \
  > current_attempt/corpus/discovered/maven_j17_fresh.txt
wc -l current_attempt/corpus/discovered/maven_j17_fresh.txt
git add current_attempt/corpus/discovered && git commit -m "discover: fresh J17 maven candidates"
```

---

## 3. Validate candidates → baselines

A declared version isn't a baseline until it builds. For each candidate, **shallow-fetch unshallowed**
(so commit history is real), walk commits in **seeded-random** order, and accept the **first** commit
that test-compiles under its `jv_from`. Cheap-reject for free: no build file, or already ≥ `jv_to`.
Cap ~10 compile attempts and a scan cap on commits inspected.

The compile check, per build tool:

```bash
# Maven
JAVA_HOME=<jdk_from> mvn -q -B -ntp -DskipTests test-compile
# Gradle — the wrapper's Gradle version must support jv_from (JDK 21 → Gradle 8.5+, JDK 17 → 7.3+);
# if it's too old, `./gradlew wrapper --gradle-version <X>` first, or the build won't even start.
JAVA_HOME=<jdk_from> ./gradlew -q --no-daemon testClasses
```

`test-compile`/`testClasses` (main+test) is the validity bar — never admit a baseline whose tests
don't even compile. Record each accepted `{repo, sha, jv_from, stars}` (stars via
`gh api repos/<owner>/<name> --jq .stargazers_count`). Sample **most-stars-first** so a bounded run
keeps the highest-signal baselines.

---

## 4. Fold into the corpus

- Merge accepted baselines into the **attempt-db** `current_attempt/corpus/attempt_db.json` (repo+sha
  keyed by `jv_from`) — the cache of every baseline ever mined.
- Draw the per-run **iter-db** `current_attempt/dataset-shas.json` (the sweep's active corpus, ~100
  per hop) from the attempt-db rather than re-digging. Dig only the thin cells.

---

## 5. State, gotchas, when to stop

- **Code-search is a floor, not a census:** default branch + indexed repos only; misses versions set
  in a parent POM or convention plugin. Dedup is only as good as §1 — rebuild `known.txt` each run.
- **Gradle validation/bump is the open frontier.** The compile check in §3 is written but
  **untested**; the wrapper↔JDK compatibility is the footgun — build + run it against a real
  `gradle_j*_fresh.txt` repo before trusting it. The Gradle *bump* (OpenRewrite via the
  `rewrite-gradle-plugin` init-script + `gradle rewriteRun`, conserve via `gradle test`) and a Gradle
  track in the `bump-java-version` SKILL.md are still to write — test-first.
- **Already in `corpus/discovered/` (fresh new-unique, deduped this round):** Maven J17≈3431 J21≈3293;
  Gradle J17≈2900 J21≈2823 — far more than the ~100/hop the iter-db needs, so **validation (§3), not
  discovery, is now the bottleneck.**
- **Stop discovering** a (version, build tool) once `corpus/discovered/` holds well over 100/hop with
  margin for validation fallout; re-enter only to fill a genuinely thin cell (J21/J25, or a new build
  tool).

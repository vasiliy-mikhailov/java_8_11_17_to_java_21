---
name: discover-bump-dataset
description: Discover and expand the training dataset of real GitHub repos used to evaluate and harden the bump-java-version skill. Finds FRESH unique Maven or Gradle projects that declare a given Java LTS (8/11/17/21) via GitHub code-search, dedupes them against the corpus we already have, and validates which actually compile into baselines. Use when growing the corpus, filling a Java-version gap (e.g. need more J17/J21 baselines), or adding a build tool (Gradle). This is harness tooling — NOT the portable bump-java-version skill.
---

# Discover the bump-java-version training dataset

Find real GitHub repos that **declare** a target Java version, dedupe against everything we already
have, and **validate** which ones compile into baselines — to grow the corpus the `bump-java-version`
skill is scored against (P4). Two build tools: **Maven** (`pom.xml`) and **Gradle** (`build.gradle` /
`.kts`). Candidates are *not* baselines until validated.

Repo root: `/home/vmihaylov/java_8_11_17_to_java_21` (the open attempt is `current_attempt/`).

---

## 0. Tools

- **`gh` CLI**, authenticated (`gh auth status`). Discovery uses GitHub **code-search** through `gh
  api` — the sanctioned GitHub path, never raw `curl`/`urllib` to scrape.
- **`python3`** for the discovery + validation drivers (all under `current_attempt/tools/`).
- The two JDKs + Maven/Gradle for the validation step (same toolchain the bump skill uses).

---

## 1. Discover candidates (GitHub code-search, deduped)

Run the committed discovery drivers. They build a **known set** (~10k+ repos) from
`dataset-repos.json` + `dataset-shas.json` + `corpus/attempt_db.json` + every `~/*dig*.json` +
existing candidate lists, search code for version markers, and write only repos **not** already known.

```bash
cd /home/vmihaylov/java_8_11_17_to_java_21
GITHUB_TOKEN=$(gh auth token) python3 current_attempt/tools/discover_maven.py        # → /tmp/j{17,21}_fresh3.txt
GITHUB_TOKEN=$(gh auth token) python3 current_attempt/tools/discover_gradle.py 17,21  # → /tmp/gradle_j{17,21}_fresh.txt
```

**Search markers** (anchored so code-search tokenizes them; `language:Java` is dropped — it zeroes out
combined with the angle-bracket phrase):
- **Maven** — `filename:pom.xml` + `"<java.version>N<"`, `"<maven.compiler.source>N<"`,
  `"<maven.compiler.target>N<"`, `"<maven.compiler.release>N<"`.
- **Gradle** — `filename:build.gradle` AND `filename:build.gradle.kts` (separate queries — `.kts` is a
  different filename), each with `"JavaLanguageVersion.of(N)"` (toolchain DSL, Groovy+Kotlin) and
  `"JavaVersion.VERSION_N"` (source/targetCompatibility).

**Rate limit — the one hard rule:** GitHub search API is **30 requests/min per token**. The drivers
sleep 2.2s between pages and 60s on a 429. **Run Maven and Gradle discovery sequentially, never
concurrently** — they share the one limit and will starve each other. Chain them by polling
`pgrep -f discover_maven` before starting the Gradle run.

Persist the fresh lists out of `/tmp` into `current_attempt/corpus/discovered/` and commit — `/tmp` is
ephemeral.

---

## 2. Validate candidates → baselines

A candidate only *declares* a version; confirm it actually builds. `sample_shas.py` clones each repo,
walks seeded-random commits, and keeps the first that **test-compiles** under `jv_from`.

**Maven** (works today):
```bash
python3 current_attempt/tools/sample_shas.py --only-from=17 --seed=0 --max-attempts=5 --scan-cap=70 \
  --repos-file=current_attempt/corpus/discovered/maven_j17_fresh.txt --out=/home/vmihaylov/j17dig2.json
```
It rejects junk for free (no build file / already ≥ jv_to / non-compiling), so only real baselines
`{repo, sha, jv_from, stars}` land in `--out`.

**Gradle** (pending — see §4): `sample_shas.py` is Maven-only. The Gradle path must detect
`build.gradle`/`.kts`, parse the declared jv, and validate via `./gradlew testClasses` under a JDK
whose **wrapper version supports it** (JDK 21 → Gradle 8.5+, JDK 17 → 7.3+) — build + test it against a
real `gradle_j*_fresh.txt` repo before trusting it.

---

## 3. Fold into the corpus

- Merge validated baselines into the **attempt-db** `current_attempt/corpus/attempt_db.json`
  (repo+sha keyed by `jv_from`) — the cache of every baseline ever mined.
- Draw the per-run **iter-db** `current_attempt/dataset-shas.json` (the sweep's active corpus, N≈100
  per hop) from the attempt-db rather than re-digging. Dig only the gaps (e.g. thin J21 / no J25).

---

## 4. Gotchas & current state

- **Code-search coverage** is the default branch only and indexed-repos only — counts are a floor, not
  a census. Markers miss repos that set the version in a convention plugin or parent POM.
- **Dedup is only as good as the known set** — always rebuild it from the live corpus files before a
  run, or you re-surface repos you already have.
- **Gradle validation/bump is not built yet.** Pending work: the `sample_shas.py` Gradle path (§2),
  the `oh_drive.py` Gradle bump (OpenRewrite via `rewrite-gradle-plugin` init-script + `gradle
  rewriteRun`, conserve via `gradle test`), and a Gradle track in the `bump-java-version` SKILL.md —
  all test-first against a discovered Gradle repo (the wrapper↔JDK compat is the footgun).
- **Found this session (fresh new-unique, deduped):** Maven J17=3431 J21=3293; Gradle J17=2900
  J21=2823 — in `current_attempt/corpus/discovered/`. Far more than the ~100/hop the iter-db needs, so
  validation (not discovery) is now the bottleneck.

---

## 5. When to stop

Stop discovering a (version, build tool) once `corpus/discovered/` holds well more than the iter-db
needs (≈100/hop with margin for validation fallout). Then the work shifts to §2 validation and §3
folding. Re-enter discovery only to fill a genuinely thin cell (e.g. J21/J25, or a newly-added build
tool).

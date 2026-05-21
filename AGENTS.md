# AGENTS.md

**Writing to the agent:** Prefer compact fitness functions and constraints over implementation instructions; the agent is capable of filling the gaps itself because it has tool access, internet search, sandboxed execution, verification, and iterative repair capabilities.

1. **Workdir:** `$HOME/java_8_11_17_to_java_21`.
2. **Containment:** all language toolchains (JDK / Maven / Gradle / OpenRewrite) and recipe execution run inside Docker.
3. **Fitness (recipe):** produce an OpenRewrite recipe composition that translates Java 8 / 11 / 17 codebases — across the popular dependencies whose breaking changes OpenRewrite targets — into clean Java 21 builds with their tests passing, evaluated on every entry of `java21-migration-dataset.json`.
4. **Fitness (vLLM spin-up):**
   - `curl https://inference.mikhailov.tech/v1/models` lists `qwen3.6-27b-fp8`.
   - Weights loaded from `/mnt/steam/forge/shared/models`, no re-download.
   - Tool-call smoke returns parsed `tool_calls` (parser: `qwen3_xml`).
5. **Fitness (dataset rediscovery):** rediscover `java21-migration-dataset.json` such that every entry is (a) clone-and-checkout reproducible from `commit_sha` alone (resolved SHA, no prose), (b) baseline-buildable inside the runner container on its declared Java version, (c) genuinely uses the column's dependency family in source files, (d) permissively licensed (Apache-2.0 / MIT / BSD / EPL), and (e) the matrix has ≥2 distinct-owner samples per (Java version × dependency family) cell. The columns are the OpenRewrite-targeted dependencies whose breaking changes matter most for Java 21 migration.

# AGENTS.md

**Writing to the agent:** Prefer compact fitness functions and constraints over implementation instructions; the agent is capable of filling the gaps itself because it has tool access, internet search, sandboxed execution, verification, and iterative repair capabilities.

1. **Workdir:** `$HOME/java_8_11_17_to_java_21`.
2. **Containment:** all language toolchains (JDK / Maven / Gradle / OpenRewrite) and recipe execution run inside Docker.
3. **Access:** SSH to the work host is multiplexed (ControlMaster + ControlPath + ControlPersist) so every call in a session reuses one TCP + auth handshake instead of dialling out per command.
4. **Fitness (recipe):** find the OpenRewrite recipe composition that produces the highest-quality Java 21 conversion of every repo in `java21-migration-dataset.json` — where "high quality" is whatever the agent reasons it should mean in this domain. Crafted through a ralph loop (apply → check → improve), with trajectory and per-recipe-by-cell contribution as first-class outputs.
5. **Fitness (vLLM spin-up):** stand up the endpoint until all three observables hold; arrive there through a ralph loop (try → check → adjust) over container flags, model args, mounts, and reverse-proxy config.
   - `curl https://inference.mikhailov.tech/v1/models` lists `qwen3.6-27b-fp8`.
   - Weights loaded from `/mnt/steam/forge/shared/models`, no re-download.
   - Tool-call smoke returns parsed `tool_calls` (parser: `qwen3_xml`).
6. **Fitness (dataset rediscovery):** curate `java21-migration-dataset.json` as 2-5 distinct-owner samples per (Java version × dependency family) cell, where Java version ∈ {8, 11, 17} and dependency family ∈ the popular dependencies that OpenRewrite targets as having breaking changes for Java 21 migration. Each entry is clone-and-checkout reproducible from `commit_sha` alone, baseline-buildable inside the runner container on its declared Java version, genuinely uses the cell's dependency family in source, and permissively licensed (Apache-2.0 / MIT / BSD / EPL). Iterate candidate repos through a ralph loop, balancing the matrix.

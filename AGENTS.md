# AGENTS.md

**Writing to the agent:** Prefer compact fitness functions and constraints over implementation instructions; the agent is capable of filling the gaps itself because it has tool access, internet search, sandboxed execution, verification, and iterative repair capabilities.

1. **Workdir:** `$HOME/java_8_11_17_to_java_21`.
2. **Containment:** all language toolchains (JDK / Maven / Gradle / OpenRewrite) and recipe execution run inside Docker. If a host resource this project needs (port, mount, GPU memory, …) is held by something unrelated, free it in favour of this project.
3. **Access:** SSH to the work host is multiplexed (ControlMaster + ControlPath + ControlPersist) so every call in a session reuses one TCP + auth handshake instead of dialling out per command.
4. **Fitness (recipe):** find the OpenRewrite recipe composition that produces the highest-quality Java 21 conversion of every repo in `java21-migration-dataset.json` — where "high quality" is whatever the agent reasons it should mean in this domain. Crafted through a ralph loop (apply → check → improve), with trajectory and per-recipe-by-cell contribution as first-class outputs.
5. **Fitness (vLLM spin-up):** stand up the endpoint until all five observables hold; arrive there through a ralph loop (try → check → adjust) over container flags, model args, mounts, and reverse-proxy config. An existing Caddy already owns `:443` on this host for other services.
   - `curl https://inference.mikhailov.tech/v1/models` lists `qwen3.6-27b-fp8`.
   - Served with a 128k-token context window (`max_model_len ≈ 131072`).
   - Weights loaded from `/mnt/steam/forge/shared/models`, no re-download.
   - Tool-call ping/pong smoke: a `POST /v1/chat/completions` request offering a single `ping(message: string)` tool, with the user message "say ping via the tool", yields `choices[0].message.tool_calls[0].function.name == "ping"` parsed structurally (vLLM's `--tool-call-parser` must be the one that matches Qwen 3.6's native tool-call output).
   - No access without `VLLM_API_KEY` from `.env`: unauthenticated requests are rejected; requests bearing the key succeed.
6. **Fitness (dataset rediscovery):** curate `java21-migration-dataset.json` as 2-5 distinct-owner samples per (Java version × dependency family) cell, where Java version ∈ {8, 11, 17} and dependency family ∈ the popular dependencies that OpenRewrite targets as having breaking changes for Java 21 migration. Each entry is clone-and-checkout reproducible from `commit_sha` alone, baseline-buildable inside the runner container on its declared Java version, genuinely uses the cell's dependency family in source, and permissively licensed (Apache-2.0 / MIT / BSD / EPL). Iterate candidate repos through a ralph loop, balancing the matrix.

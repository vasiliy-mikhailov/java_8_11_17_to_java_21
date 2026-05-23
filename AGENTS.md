# AGENTS.md

**Per-attempt history:** each `attempt_N/README.md` is a historical snapshot of the AGENTS.md state under which that attempt ran. It is not read by the agent — it exists only for audit.

**Fitness structure:**
- **Writing this file** (item 0): the meta-fitness governing AGENTS.md itself.
- Operational (items 1–3): workdir, containment, access — preconditions every iteration must respect.
- **Recipe** (item 4): the primary fitness — find the OpenRewrite recipe composition that produces the highest-quality Java 21 conversion of the dataset. May be single-jump or staged across intermediate JDKs.
- **vLLM spin-up** (item 5): the inference endpoint observables, ralph-looped over container / proxy config until satisfied.
- **Dataset rediscovery** (item 6): the corpus the recipe fitness measures against, ralph-looped over candidate repos.
- **Per-failing-repo refinement** (item 7): a finer-grained ralph loop nested under the recipe fitness. Used when the coarse loop plateaus on the build-success metric.
- **Runner saturation** (item 8): keep the verifier host loaded enough to make progress without thrashing.

0. **Fitness (writing this file):** keep AGENTS.md compact and outcome-named so the agent re-derives the *how* every iteration from its tools and the corpus.
   - **Constraints:** no implementation instructions the agent can fill itself, no enumerations that age, no justifications for the rule alongside the rule.
   - **Search:** read → why → intent — when revisiting a clause, ask "why is this here?"; if the answer is implementation detail, enumeration, or justification, strip it back to the rule itself.
   - **Reward:** cuts that lose words without losing the rule.
   - **Repeat:** every editing pass.
1. **Workdir:** `$HOME/java_8_11_17_to_java_21`.
2. **Containment:** all build toolchains and recipe execution run inside Docker. If a host resource this project needs is held by something unrelated, free it in favour of this project. Cache external downloads on a host-side bind mount shared across containers, and let the cache survive across iterations.
3. **Access:** SSH calls to the work host share one session, not one per command.
4. **Fitness (recipe):** find the OpenRewrite recipe composition that produces the highest-quality Java 21 conversion of every repo in `java21-migration-dataset.json` — where "high quality" is whatever the agent reasons it should mean in this domain. The composition may be a single-jump recipe applied under JDK 21, or split across N stage recipes per intermediate JDK target — when staged, each stage's recipes and dependency versions must be compatible with that stage's Java version, and each stage's pom and source edits persist into the next stage's working tree. Declarative YAML recipes only — chain OpenRewrite catalog primitives and pre-built migration recipes; no custom Java AST recipes that would require compiling and shipping a recipe JAR. Crafted through a ralph loop (apply → check → improve). When this coarse loop plateaus on the corpus build-success metric, refine through item 7.
5. **Fitness (vLLM spin-up):** stand up an OpenAI-compatible chat-completion endpoint serving Qwen 3.6 27B FP8 that the agent can call from inside Docker containers, with a context window large enough for a unified repo diff plus prompt overhead, tool calls round-tripping structurally, and authentication enforced by an API key. Arrive there through a ralph loop over container flags, model args, mounts, and reverse-proxy config; don't conflict with services already bound on this host.
6. **Fitness (dataset rediscovery):** curate `java21-migration-dataset.json` as 24 distinct-owner samples per (Java version × dependency family) cell, where Java version ∈ {8, 11, 17} and dependency family ∈ the popular dependencies that OpenRewrite targets as having breaking changes for Java 21 migration. Each entry is clone-and-checkout reproducible from `commit_sha` alone, baseline-buildable inside the runner container on its declared Java version, and genuinely uses the cell's dependency family in source. Prefer smaller repos to keep cycle time tight. If a cell can't be filled from current-state repos, search git history for older commits that match. Iterate candidates through a ralph loop, balancing the matrix.
7. **Fitness (per-failing-repo refinement):** raise the corpus build-success rate past where coarse recipe mutations plateau, leveraging vLLM Qwen 3.6 27B FP8 and Claude as solution-finder + judges throughout.
   - **Constraints:** declarative configuration deltas only.
   - **Search:** ground each candidate fix in a known community workaround.
   - **Reward:** real `build_post 0 → 1` flips net of regressions on the full corpus.
   - **Repeat:** simplest cluster first; stop when only bespoke engineering remains.
8. **Fitness (runner saturation):** keep the verifier host CPU between 60 % and 80 % of cores *while items 4 / 6 / 7 are running* — this fitness composes with them rather than standing alone — saturation only counts toward the composite objective when a parent loop is making progress.
   - **Constraints:** any concurrency dial the agent can reach.
   - **Search:** sample load periodically, decide what to adjust given the recent action history and which parent loop is active.
   - **Reward:** sustained band hit without thrashing or stalling the parent loop.
   - **Repeat:** continuous, dampened against oscillation; pause when no parent loop is active.

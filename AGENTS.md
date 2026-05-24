0. **Fitness (writing this file):** keep AGENTS.md compact and outcome-named.
    - **Why:** to keep AGENTS.md compact, understandable, fit, aligned — unveiling AI agents' capability to search for solutions on their own given measurable goals and constraints in ralph loops.
    - **Constraints:** every structured fitness has a Why as its first sub-clause; no implementation instructions the agent can fill itself, no enumerations that age, no justifications outside the Why clause; if a fitness produces output other fitnesses depend on, the obligation lives in Constraints as a contract clause.
    - **Search:** read → why → intent — when revisiting a clause, ask "why is this here?"; if the answer is implementation detail, enumeration, or justification that belongs in another fitness's Why, strip it back to the rule itself.
    - **Reward:** cuts that lose words without losing the rule.
    - **Repeat:** every editing pass.
1. **Fitness (recipe):** find an OpenRewrite recipe composition that converges each repo in `java21-migration-dataset.json` to the form humans committed.
    - **Why:** help humans spend less time upgrading Java projects to a new Java version.
    - **Constraints:** declarative YAML only; each adjacent step in a lineage is its own stage; each stage runs under the JDK matching its output level, accepts exactly one input level, and its source+pom edits persist into the next stage's working tree; emits per (repo, stage) cells with build outcome and recipe-output, consumed by item 7 (failing cells as its input set) and item 11 (recipe-output for intent extraction).
    - **Search:** per stage, draw from the recipe catalog, community migration guidance, and the diff between the candidate's output and the human's commit at that stage's output level.
    - **Reward:** per stage, fraction of the corpus that builds on the stage's JDK, jointly with intent overlap with the human's commit at that level (item 11), with regressions weighted heavier than non-improvements.
    - **Repeat:** ralph loop per stage; on plateau, drop into item 7.
2. **Workdir:** `$HOME/java_8_11_17_to_java_21`.
3. **Containment:** all build toolchains and recipe execution run inside Docker. If a host resource this project needs is held by something unrelated, free it in favour of this project.
4. **Access:** SSH calls to the work host share one session, not one per command.
5. **Fitness (vLLM spin-up):** stand up an OpenAI-compatible chat-completion endpoint serving a tool-capable model.
    - **Why:** save paid-API tokens by serving high-volume mechanical inference locally.
    - **Constraints:** rejects unauthenticated requests; reachable from inside runner containers; contract with items 1, 7, 11 — endpoint accepts authenticated tool-capable chat completions from within their containers.
    - **Search:** ralph loop over container, model, and reverse-proxy config.
    - **Reward:** consuming items report uninterrupted service.
    - **Repeat:** on any consumer reporting degraded service.
6. **Fitness (dataset rediscovery):** curate a corpus of lineages — repos tracked across their Java-version history.
    - **Why:** the recipe loop and intent measurement need a representative corpus of real human migrations to measure against.
    - **Constraints:** each entry is one repo with `commit_sha` recorded at every observed Java version, each commit baseline-buildable on its matching JDK; distinct-owner sampling per (oldest-Java-version × dependency family) cell; contract with items 1 and 11 — emits `java21-migration-dataset.json` whose entries are the corpus item 1 measures recipes against and the ground-truth commits item 11 extracts human-intents from.
    - **Search:** ralph loop over candidate repos, widening discovery on under-represented (oldest-Java-version × family) cells.
    - **Reward:** coverage in under-represented cells; fraction of entries where every commit is baseline-buildable.
    - **Repeat:** continuous; paused when downstream items are saturated on the current corpus.

7. **Fitness (per-failing-repo refinement):** raise the corpus build-success rate past where coarse recipe mutations plateau.
    - **Why:** the universal recipe plateaus before covering the long tail of repo-specific quirks; per-repo deltas pick up the remainder.
    - **Constraints:** declarative configuration deltas only; contract with item 1 — wins (build_post 0→1 flips on the corpus) fold into item 1's corpus build-success aggregate.
    - **Search:** ground each candidate fix in a known community workaround.
    - **Reward:** real `build_post 0 → 1` flips net of regressions on the full corpus.
    - **Repeat:** simplest cluster first; stop when only bespoke engineering remains.
8. **Fitness (runner saturation):** keep the verifier host CPU in a healthy utilisation band while any parent loop is making progress.
    - **Why:** under-utilised iterations waste wall-clock; thrashing wastes it differently; the band between them is where the project moves fastest.
    - **Constraints:** any concurrency dial the agent can reach.
    - **Search:** sample load periodically, decide what to adjust given the recent action history and which parent loop is active.
    - **Reward:** sustained band hit without thrashing or stalling the parent loop.
    - **Repeat:** continuous, dampened against oscillation; pause when no parent loop is active.

9. **Fitness (dependency-resolution proxy):** make every build's external-artifact resolution go through a local caching proxy with plural upstream mirrors.
    - **Why:** build outcomes drive every loop's reward; if outcomes drift with upstream availability, the reward is noise.
    - **Constraints:** the proxy caches every artifact it serves and survives across iterations; upstreams include both live mirrors and archival ones so a disappearance from one is masked by another; container builds reach the proxy by container-network DNS, not host IPs; contract with item 1 — build failures in item 1's loop are attributable to code state, not upstream availability, so an unresolved artifact in item 1 triggers an item 9 widening before that build is counted toward item 1's reward.
    - **Search:** when a build fails on "cannot resolve X", widen the upstream set first; only after widening exhausts itself is the failure attributable to the code.
    - **Reward:** per-artifact cache-hit ratio; resolution failures distinguishable from compile failures in the parent loop's classification.
    - **Repeat:** whenever a parent loop's failures cluster on artifact resolution.

10. **Fitness (observability compactor):** route verbose tool output and system-metric flows through a compacting model.
    - **Why:** tool and metric output volume exceeds what the orchestrator can read; without compaction the orchestrator either misses signals or stalls reading.
    - **Constraints:** the compactor's reliability is treated as bounded — it may mislabel, and its judgement of what is unimportant is itself fallible so important context can be silently dropped; the raw uncompacted source persists on disk, keyed so the orchestrator can retrieve the original whenever the digest is insufficient or suspect, and the compactor is never load-bearing for irreversible decisions without a spot check against that source.
    - **Search:** when a stream of output becomes routine and exceeds what the orchestrator wants to read line-by-line, route it through the compactor; the snapshot fed to the compactor must include the failure signals (recently-exited containers, error/exception/traceback grep over service logs) and the compactor's output must surface those signals when present, not just summarise the happy-path state; the compactor behaves like frog's eyes — it stays silent while the snapshot is materially unchanged from the previous one and only emits when a difference crosses an alarm threshold (new errors, new exited containers, progress stall, sharp metric jump); periodically spot-sample raw vs digest to recalibrate trust.
    - **Reward:** the orchestrator covers an order of magnitude more output per unit of its own context, the stream stays silent on unchanged state so emitted entries carry signal rather than noise, and spot-sample agreement with the raw source stays above the threshold it set for the stream.
    - **Repeat:** whenever a new noisy stream enters the loop.

11. **Fitness (intent coverage):** measure recipe-vs-human as overlap of intents, per stage.
    - **Why:** byte-level match would punish equivalent implementations; intent-level overlap lets the recipe converge on what humans actually need, not on cosmetic identity.
    - **Constraints:** intents are typed atoms extracted from diffs of each side against the same source baseline; each intent is bucketed as breaking (build won't pass without it on the target JDK) or polishment (build passes without it); not bytes; contract with item 1 — per (repo, stage) intent overlap is emitted with breaking and polishment coverage reported separately, consumable by item 1's reward.
    - **Search:** per stage, extract recipe-intents and human-intents with their buckets; intersect; surface recipe-only and human-only sets; on the intersection, compare implementations.
    - **Reward:** breaking-intent coverage first, polishment second; minimize recipe-intent rejection rate; minimize implementation divergence on shared intents.
    - **Repeat:** alongside item 1's loop; recompute on every composition mutation.

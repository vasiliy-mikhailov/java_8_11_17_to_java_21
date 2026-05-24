0. **Fitness function: keep AGENTS.md compact and aligned**
    - **Why exists:** to keep AGENTS.md compact, understandable, fit, aligned — unveiling AI agents' capability to search for solutions on their own given measurable goals and constraints in ralph loops.
    - **Contract and constraints:** every item has a Why exists as its first sub-clause; no implementation instructions the agent can fill itself, no enumerations that age, no justifications outside the Why clause; search hints are only the parts an intelligent agent can't infer on its own; if a fitness produces output other fitnesses depend on, the obligation lives in this clause as a contract.
    - **Search hints:** read → why → intent — when revisiting a clause, ask "why is this here?"; if the answer is implementation detail, enumeration, or justification that belongs in another fitness's Why, strip it back to the rule itself.
    - **Reward:** cuts that lose words without losing the rule.
    - **Repeat:** every editing pass.
1. **Fitness function: discover Java migration recipe**
    - **Why exists:** help humans spend less time upgrading Java projects to a new Java version.
    - **Contract and constraints:** the recipe is an OpenRewrite YAML composition that converges each repo in `java21-migration-dataset.json` to the form humans committed; each adjacent step in a lineage is its own stage; each stage runs under the JDK matching its output level, accepts exactly one input level, and its source+pom edits persist into the next stage's working tree; emits per (repo, stage) cells with build outcome and recipe-output, consumed by item 5 (failing cells as its input set) and item 9 (recipe-output for intent extraction).
    - **Search hints:** per stage, draw from the recipe catalog, community migration guidance, the corpus's empirical human-intent catalog (item 4), and the diff between the candidate's output and the human's commit at that stage's output level.
    - **Reward:** per stage, fraction of the corpus that builds on the stage's JDK, jointly with intent overlap with the human's commit at that level (item 9), with regressions weighted heavier than non-improvements.
    - **Repeat:** ralph loop per stage; on plateau, drop into item 5.
2. **Fitness function: maintain local environment**
    - **Why exists:** iterations need predictable performance, predictable locations, and freedom from external rate-limit interruptions.
    - **Contract and constraints:** the environment must be fast to use, hard to get banned, and consistent about where things live; known paths for project workdir (`$HOME/java_8_11_17_to_java_21`) and corpus repo-mirror cache (`/var/cache/git-mirrors/<owner>/<repo>.git`); all build toolchains and recipe execution run inside Docker; SSH calls share one session per work-host, not one per command; free host resources held by unrelated work when the project needs them.
    - **Search hints:** when a pattern is repeated and slow, pin a known location or cache for it; when a pattern risks an external rate-limit, cache the upstream once.
    - **Reward:** zero ban incidents; predictable per-iteration wall-clock; locations re-used across iterations.
    - **Repeat:** whenever a new noisy or slow pattern emerges.
3. **Fitness function: serve local LLM endpoint**
    - **Why exists:** save paid-API tokens.
    - **Contract and constraints:** the endpoint is OpenAI-compatible chat-completion serving a tool-capable model; rejects unauthenticated requests; reachable from inside runner containers; contract with items 1, 5, 9 — endpoint accepts authenticated tool-capable chat completions from within their containers.
    - **Search hints:** ralph loop over container, model, and reverse-proxy config.
    - **Reward:** consuming items report uninterrupted service.
    - **Repeat:** on any consumer reporting degraded service.
4. **Fitness function: curate migration corpus**
    - **Why exists:** the recipe loop and intent measurement need a representative corpus of real human migrations to measure against, and a catalog of the intents humans actually expressed in those migrations.
    - **Contract and constraints:** the corpus consists of lineages — repos tracked across their Java-version history; each entry is one repo with `commit_sha` recorded at every observed Java version, each commit baseline-buildable on its matching JDK; distinct-owner sampling per (oldest-Java-version × dependency family) cell; contract with items 1 and 9 — emits `java21-migration-dataset.json` whose entries are the corpus item 1 measures recipes against, plus per (repo, stage) human-intent extracts (kind, general_idea, human_impl, bucket) that item 1 draws from as search priors and item 9 uses as the reference side of intent overlap.
    - **Search hints:** ralph loop over candidate repos, widening discovery on under-represented (oldest-Java-version × family) cells.
    - **Reward:** coverage in under-represented cells; fraction of entries where every commit is baseline-buildable.
    - **Repeat:** continuous; paused when downstream items are saturated on the current corpus.

5. **Fitness function: refine per failing repo**
    - **Why exists:** the universal recipe plateaus before covering the long tail of repo-specific quirks.
    - **Contract and constraints:** raise the corpus build-success rate past where coarse recipe mutations plateau; declarative configuration deltas only; contract with item 1 — wins (build_post 0→1 flips on the corpus) fold into item 1's corpus build-success aggregate.
    - **Search hints:** ground each candidate fix in a known community workaround.
    - **Reward:** real `build_post 0 → 1` flips net of regressions on the full corpus.
    - **Repeat:** simplest cluster first; stop when only bespoke engineering remains.
6. **Fitness function: saturate the runner**
    - **Why exists:** under-utilised iterations waste wall-clock; thrashing wastes it differently; the band between them is where the project moves fastest.
    - **Contract and constraints:** keep the verifier host CPU in a healthy utilisation band while any parent loop is making progress; any concurrency dial the agent can reach.
    - **Search hints:** sample load periodically, decide what to adjust given the recent action history and which parent loop is active.
    - **Reward:** sustained band hit without thrashing or stalling the parent loop.
    - **Repeat:** continuous, dampened against oscillation; pause when no parent loop is active.

7. **Fitness function: proxy dependency resolution**
    - **Why exists:** build outcomes drive every loop's reward; if outcomes drift with upstream availability, the reward is noise.
    - **Contract and constraints:** every build's external-artifact resolution goes through a local caching proxy with plural upstream mirrors; the proxy caches every artifact it serves and survives across iterations; upstreams include both live mirrors and archival ones so a disappearance from one is masked by another; container builds reach the proxy by container-network DNS, not host IPs; contract with item 1 — build failures in item 1's loop are attributable to code state, not upstream availability, so an unresolved artifact in item 1 triggers an item 7 widening before that build is counted toward item 1's reward.
    - **Search hints:** when a build fails on "cannot resolve X", widen the upstream set first; only after widening exhausts itself is the failure attributable to the code.
    - **Reward:** per-artifact cache-hit ratio; resolution failures distinguishable from compile failures in the parent loop's classification.
    - **Repeat:** whenever a parent loop's failures cluster on artifact resolution.

8. **Fitness function: compact observations**
    - **Why exists:** tool and metric output volume exceeds what the orchestrator can read; without compaction the orchestrator either misses signals or stalls reading.
    - **Contract and constraints:** verbose tool output and system-metric flows are routed through a compacting model; the compactor's reliability is treated as bounded — it may mislabel, and its judgement of what is unimportant is itself fallible so important context can be silently dropped; the raw uncompacted source persists on disk, keyed so the orchestrator can retrieve the original whenever the digest is insufficient or suspect, and the compactor is never load-bearing for irreversible decisions without a spot check against that source.
    - **Search hints:** when a stream of output becomes routine and exceeds what the orchestrator wants to read line-by-line, route it through the compactor; the snapshot fed to the compactor must include the failure signals (recently-exited containers, error/exception/traceback grep over service logs) and the compactor's output must surface those signals when present, not just summarise the happy-path state; the compactor behaves like frog's eyes — it stays silent while the snapshot is materially unchanged from the previous one and only emits when a difference crosses an alarm threshold (new errors, new exited containers, progress stall, sharp metric jump); periodically spot-sample raw vs digest to recalibrate trust.
    - **Reward:** the orchestrator covers an order of magnitude more output per unit of its own context, the stream stays silent on unchanged state so emitted entries carry signal rather than noise, and spot-sample agreement with the raw source stays above the threshold it set for the stream.
    - **Repeat:** whenever a new noisy stream enters the loop.

9. **Fitness function: measure intent coverage**
    - **Why exists:** byte-level match would punish equivalent implementations.
    - **Contract and constraints:** recipe-vs-human is measured as overlap of intents, per stage; intents are typed atoms extracted from diffs of each side against the same source baseline; each intent is bucketed as breaking (build won't pass without it on the target JDK) or polishment (build passes without it); not bytes; contract with item 1 — per (repo, stage) intent overlap is emitted with breaking and polishment coverage reported separately, consumable by item 1's reward.
    - **Search hints:** per stage, extract recipe-intents and human-intents with their buckets; intersect; surface recipe-only and human-only sets; on the intersection, compare implementations; aggregate per-stage across the corpus to surface the most-requested breaking intents and the least-covered ones.
    - **Reward:** breaking-intent coverage first, polishment second; minimize recipe-intent rejection rate; minimize implementation divergence on shared intents.
    - **Repeat:** alongside item 1's loop; recompute on every composition mutation.

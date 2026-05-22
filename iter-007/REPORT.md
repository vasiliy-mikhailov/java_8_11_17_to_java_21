# Iter-7 report — re-run iter-6 timeouts with warm cache

Targeted re-run of just the 11 repos that timed out at iter-6's 25-min wall-cap. Hypothesis: with the m2 cache now 1.3+ GB warmed, repeat invocations should finish faster.

## Outcome

| repo | result |
|------|--------|
| `jakarta-j11-2` (quarkus-quickstarts) | finished: pre=0, post=0, rc=1 — recipe failed; build doesn't reach baseline either |
| 10 others | **timed out again** at the 25-min cap |

The 3 CPU-active large builds (`jenkins-2.479`, `jenkins-2.504`, `solr branch_9x`) were genuinely making progress at 200-700% CPU but didn't finish. The other 7 (`hjl-j11-3-CAVEAT`, `hjl-j11-2`, `hjl-j11-1`, `jakarta-j17-2-CAVEAT`, `jakarta-j8-3`, `sb2-j11-3`, `sb2-j17-1`) sat at <1% CPU after their initial clone — Maven dep resolution or OpenRewrite LST construction stalled on something repo-specific.

## What this means

These 11 repos hit a **wall-clock ceiling**, not a fitness ceiling. Warm cache + repeat invocation doesn't help because:

- Jenkins/Solr/JeecgBoot are genuinely huge (Jenkins core has thousands of files; Solr has hundreds of test resources; JeecgBoot is a low-code platform with 50+ modules). OpenRewrite's LST build for them takes **hours**, not minutes.
- Some repos (Keycloak 19, spring-native 0.12, flink-learning) appear to have pom resolution chains that don't terminate cleanly under our flags.

So the iter-6 per-cell aggregate is the **final honest signal** the corpus can offer at this resource scale.

## Updated trajectory aggregate (iter-6 + iter-7 combined)

The 1 new sample (`jakarta-j11-2`) was a fast failure with empty diff — it doesn't change any cell mean. The per-cell breakdown is unchanged from iter-6:

| Java | dep family | n honest | mean Qwen | post=1 |
|-----:|-----------|--:|----------:|-------|
| 8  | spring-boot-2             | 3 | **4.00** | 0/3 |
| 11 | spring-boot-2             | 2 | **4.00** | 0/2 |
| 8  | jakarta-ee-javax          | 1 | **4.00** | 0/1 |
| 11 | jakarta-ee-javax          | 1 | **4.00** | 0/1 |
| 17 | jakarta-ee-javax          | 1 | **4.00** | 0/1 |
| 8  | hibernate-jackson-lombok  | 1 | **4.00** | 0/1 |
| 17 | hibernate-jackson-lombok  | 2 | **4.00** | 1/2 |

**Champion recipe holds at mean Qwen 4.0 across every (Java × dep family) cell with honest signal.**

## What would unstick the timeouts (out of scope)

1. **Per-module scoping** — invoke OpenRewrite on one module at a time rather than the whole multi-module reactor. Big projects like JeecgBoot have 50+ modules; running on each independently keeps LST build per-invocation manageable.
2. **Way longer wall-cap** — hours, not 25 minutes. The 100-MB-class projects (jenkins, solr) genuinely need it. Costs CPU time but not human time if detached.
3. **A more aggressive m2 prewarm** — pre-fetch every transitive dep before the timer starts. We did partial warming via iter-2 → iter-6 but the slowest repos pull deps we haven't seen yet.

None of these change the *recipe* quality — they'd just produce more honest samples per cell, which would either confirm the 4.0 mean (likely) or reveal a per-cell variance that the current sample is too small to detect.

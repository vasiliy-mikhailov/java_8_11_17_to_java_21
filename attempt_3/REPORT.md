# attempt_3 — verified dataset @ 24-per-cell target

Goal of this attempt was to triple the per-cell sample size from attempt_2 (8 per cell, 96 repos total) to 24 per cell (288 target). Larger sample lets fitness #7 detect failure clusters that were too sparse to see at n=8 (e.g. the iter-11 / iter-12 / iter-15 / iter-16 patterns that hit only 2 repos each at attempt_2 scale).

## Verifier summary

| cell                              | passes / 24 |
|-----------------------------------|-------------|
| j8  hibernate-5                   | 24/24       |
| j8  jakarta-ee-javax              | 24/24       |
| j8  junit4-mockito                | 24/24       |
| j8  spring-boot-2                 | 24/24       |
| j11 hibernate-5                   | 24/24       |
| j11 jakarta-ee-javax              | 23/24 †     |
| j11 junit4-mockito                | 17/24 ‡     |
| j11 spring-boot-2                 | 24/24       |
| j17 hibernate-5                   | 22/24 ‡     |
| j17 jakarta-ee-javax              | 24/24       |
| j17 junit4-mockito                | 15/24 ‡     |
| j17 spring-boot-2                 | 24/24       |

Total **269 / 288** baselines (93%). 9 of 12 cells reached the 24 target.

† Pool not exhausted, verifier still grinding through JHipster-style repos with multi-minute npm-install builds. May fill to 24 if left running.

‡ Pool exhausted (j11/junit4-mockito had only 27 candidates after the distinct-owner de-dupe; j17/junit4-mockito had 20; j17/hibernate-5 had 25). Fitness #6 (history-walk corpus expansion) hit its ceiling for these (java, family) intersections at this point in time — adding more candidates would require either another search round or relaxing the distinct-owner constraint.

## Verifier improvements landed mid-run

- Subprocess `TimeoutExpired` previously orphaned the Docker child — containers leaked past the 600 s window, kept holding CPU and m2-cache locks. Patched to give each `docker run` a `--name verify-{pid}-{tid}-{ts}` and `docker kill` it from the except branch.
- BoundedSemaphore 8 → 16, ThreadPoolExecutor 12 → 20. Was leaving ~16 cores idle on a 24-core host given the 3 s p50 / 12 s mean build cost.

## Saturation diagnosis (fitness #8 outcome)

Hypotheses tested against measurement:
- **Qwen's "Maven serial reactor + m2 file-lock contention"** — wrong layer. With p25=2 s, p50=3 s, p75=16 s, p90=32 s, mean=11.8 s across 266 passing baselines, 98% of builds are not CPU-bound; they're lifecycle-bound (git clone, validate, dep-resolve from warm cache, resources phase). `-T 1C / -Dmaven.compiler.fork / parallel` flags speed up javac, which barely runs.
- **"Unrelated host npm install"** — wrong inference. The pid 153887 npm install was actually `frontend-maven-plugin` inside one of our containers; UID 0 in a container shows up as `root` in host `pidstat`. JHipster repos in the corpus (`agilekip-tutorials/buy-book` etc.) legitimately download Node 14 and run `npm install` during `mvn compile`.
- **Container-leak past timeout** — confirmed real and meaningful. Killed 4 leaks that were 28-56 minutes old.
- **Worker concurrency** — confirmed the actual lever. Each worker uses ~1-2 cores in compile-phase / npm-install / webpack peaks; the 8-worker semaphore was the binding constraint, not per-build tuning.

## Next

1. Decide whether to wait on the long-tail JHipster cell or freeze at 269.
2. Re-run the champion recipe (attempt_2 iter-13) on the 269-baseline corpus to test whether previously-bespoke failure clusters now have enough samples to be tractable under fitness #7.

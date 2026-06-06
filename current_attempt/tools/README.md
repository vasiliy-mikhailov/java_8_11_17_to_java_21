# `current_attempt/tools/`

Active toolset for the current attempt (manual-only `bump-java-version` skill + 3-agent panel).

## Dataset — pool → baselines
- **`sample_shas.py`** — the sampler. For each pool repo, walk commits and find a compiling sha
  per Java version (`--multi`), or one version (`--only-from=N`); clones from the local mirror
  (`/var/cache/git-mirrors`) or an authenticated fallback; reaps root-owned scratch via a root
  container. Emits `{repo, sha, jv_from}` (jv_to = next LTS, derived).
- **`annotate_stars.py`** — backfill each baseline with its repo's GitHub stargazer count (batched
  GraphQL); adds the `stars` field.
- **`gh_discover_8_11.py`**, **`star_rank.py`**, **`verify_green2.py`** — GitHub code-search discovery +
  star-ranking + green-baseline (`mvn test`) verification. Predecessors of the current dataset build;
  *to be consolidated with `sample_shas.py` / `annotate_stars.py`.*

## Demand (P12)
- **`find_bump_issues.py`** — the P12 request feed: OPEN GitHub issues asking to bump the Java/JDK version
  (title-matched, `language:java`), filtered to genuine bumps and enriched with the triage signals P12 needs —
  **stars**, **maintenance** (pushedAt/archived; dead repos dropped), and a **genuinely-unsatisfied** check
  (current Java version via the root pom vs the requested target; stale-open requests dropped) -> `bump_issues.json`.

## Substrate
- **`observe_rotate.py`** — size-rotates the `/var/log/observe/*` sinks (P6/P10).
- **`run_one_stage_v2.sh`** — build/test stage entry helper.

The unified 3-agent harness lives in `../portability/` (`agent_drive_one.sh`, `agent_sweep.py`,
`oh_run.py`). Superseded old-attempt tools (attempt-7/8 chain, attempt-10 single-agent OpenHands
harness, old corpus runners and triage/verdict tools) were removed — they remain in git history and
the frozen `attempt_*/` snapshots if ever needed.

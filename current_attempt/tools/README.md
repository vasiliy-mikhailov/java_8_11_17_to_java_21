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

## Substrate
- **`observe_rotate.py`** — size-rotates the `/var/log/observe/*` sinks (P6/P10).
- **`run_one_stage_v2.sh`** — build/test stage entry helper.

## `legacy/`
Old-attempt tools superseded by the manual-skill + 3-agent-panel approach, kept for reference only
(not on the active path): the attempt-7/8 OpenRewrite-chain executor (`run_sequenced_java.py`), the
attempt-10 single-agent OpenHands harness (`oh_drive.py`, `oh_one_live.py`, `oh_event_sink.py`,
`d10_outer_persist.py`), old corpus runners (`corpus_*.py`, `ladder_continuous.py`, `rerun_failed.py`),
and old triage/verdict/dataset tools (`rung1_*.py`, `reclassify_wrapper.py`, `promote.py`,
`sample_run.py`, `tune_workflow.py`, `sweep_digest.py`, `agent_stream.py`, `frog_eye.py`,
`middle_qwen.py`).

The unified 3-agent harness itself lives in `../portability/` (`agent_drive_one.sh`, `agent_sweep.py`,
`oh_run.py`).

# Corpus-best (prompt, recipes) — pointer

D2's currently-shipped Java LTS bump artifact for any tool-using coding agent.

## Artifact identity

- **prompt**: `f2cc690d6eec` → `prompt.md` (symlink to `attempt_10/prompt_snapshots/f2cc690d6eec.md`)
- **recipe catalog**: `e9d533fecf22` → `claude-recipes-1.0.0.jar` (symlink to `attempt_10/recipe_snapshots/e9d533fecf22.jar`)

## Evidence

Three D10 outer-level trajectories under this artifact (J17→J21 stages):

| stage | wall | verdict |
|---|---|---|
| 1190782_odsoft-project | 6:18 | PASS |
| j2gl_playground | 3:02 | BAIL:no_bump_commit (stale — pre buggy-verdict wrapper) |
| gal16v8d_admin-server | 2:13 | FAIL:regressed_1 (1 pre-passing test errors post-bump) |

**Current PASS rate: 1/3 = 33%** (BAIL+FAIL stages have not been escalated to D10 middle/inner yet).

## Known issues blocking better signal

1. jg trajectory ran under the verdict-buggy wrapper — verdict says BAIL but the underlying state shows pom=21 + surefire 2/0/1/0; recompute with the fixed logic (need its pre_counts) before trusting.
2. as regression on 1 test is a real signal — needs middle/inner escalation to produce an artifact update that fixes it.

## How consumers use it

Paste `prompt.md` into the agent (kilocode, cline, aider, Claude Code, OH, etc.). The agent expects a Stage header prepended (or to infer it from cwd) with `{repo, sha, jv_from, jv_to, workdir}`. The recipe JAR must be reachable to `mvn rewrite:run` calls — keep `claude-recipes-1.0.0.jar` in the local `.m2` cache before running, since it is not in Maven Central.

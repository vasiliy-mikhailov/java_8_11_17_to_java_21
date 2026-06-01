"""Score a pre/post Java-21-migration diff with the local Qwen 3.6 27B vLLM.

Invocation:
  python3 scripts/qwen_judge.py <repo_dir> [--out qwen_judgement.json]

The repo dir must be a git working tree where the OpenRewrite recipe has
already been applied (so `git diff` reflects what the recipe did). The
script:

  1. Builds a unified `git diff` (head against working tree).
  2. Sends a chat-completions request to vLLM with a single `score` tool
     defining the rubric.
  3. Writes the parsed tool_call arguments to qwen_judgement.json.

Rubric (all 1-5, higher = better):
  - idiomatic_java21: how well the migrated code uses Java 21 idioms
    (records, sealed types, switch expressions, text blocks, var,
    sequenced collections, virtual threads where natural).
  - antipattern_clearance: how completely deprecated patterns were
    removed — leftover javax.*, JUnit 4 annotations, Lombok where Java
    16+ records suffice, etc.
  - diff_coherence: does every diff line serve the migration, or is the
    recipe creating spurious churn?
  - overall: a single 1-5 capping the above as a single quality bar.

The harness's `build_post` and tests still measure correctness; this
judge measures *quality of conversion* — what the fitness contract
calls "high-quality conversion, whatever the agent reasons it should
mean in this domain".
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path


PROPOSER_BASE = os.environ.get("PROPOSER_BASE_URL", "https://inference.mikhailov.tech/qwen-3.6-27b-fp8/v1")
PROPOSER_KEY  = os.environ.get("PROPOSER_API_KEY")
MODEL     = os.environ.get("PROPOSER_MODEL", "qwen3.6-27b-fp8")
MAX_DIFF_CHARS = 90_000   # keep well under the 128k context with prompt overhead


SYSTEM = (
    "You judge Java 8/11/17 -> Java 21 migration diffs. "
    "Call the `score` tool exactly once. "
    "Be terse, evidence-grounded, and conservative — scores of 5 require "
    "near-flawless work."
)

USER_TEMPLATE = """Repo: {repo_id}
Source Java version declared: {java_version}
Dependency family targeted: {dependency_family}

Unified diff of recipe-applied changes (truncated to {max_chars} chars
if longer than the model's working budget):

```diff
{diff}
```

Score this diff with the rubric and call the `score` tool once."""

TOOL = {
    "type": "function",
    "function": {
        "name": "score",
        "description": "Record the quality scores for a Java-21 migration diff.",
        "parameters": {
            "type": "object",
            "properties": {
                "idiomatic_java21":     {"type": "integer", "minimum": 1, "maximum": 5,
                                         "description": "Use of Java 21 idioms."},
                "antipattern_clearance":{"type": "integer", "minimum": 1, "maximum": 5,
                                         "description": "Removal of deprecated patterns."},
                "diff_coherence":       {"type": "integer", "minimum": 1, "maximum": 5,
                                         "description": "Lack of spurious churn."},
                "overall":              {"type": "integer", "minimum": 1, "maximum": 5,
                                         "description": "Single-number quality cap."},
                "justification":        {"type": "string",
                                         "description": "1-2 sentences supporting the scores; cite specific lines."}
            },
            "required": ["idiomatic_java21", "antipattern_clearance", "diff_coherence",
                         "overall", "justification"]
        }
    }
}


def git_diff(repo_dir: Path) -> str:
    """Capture unstaged changes (the recipe's edits) as a unified diff."""
    cp = subprocess.run(
        ["git", "diff", "--no-color"],
        cwd=str(repo_dir), capture_output=True, text=True, check=False)
    return cp.stdout


def judge(repo_id: str, java_version: int, dependency_family: str, diff: str) -> dict:
    if not PROPOSER_KEY:
        raise SystemExit("PROPOSER_API_KEY missing — source .env first")
    if len(diff) > MAX_DIFF_CHARS:
        diff = diff[: MAX_DIFF_CHARS] + f"\n\n... [diff truncated; full length {len(diff)} chars]\n"
    user = USER_TEMPLATE.format(repo_id=repo_id, java_version=java_version,
                                 dependency_family=dependency_family,
                                 diff=diff, max_chars=MAX_DIFF_CHARS)
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user",   "content": user},
        ],
        "tools":       [TOOL],
        "tool_choice": {"type": "function", "function": {"name": "score"}},
        "temperature": 0.1,
        "max_tokens":  1024,
    }
    req = urllib.request.Request(
        f"{PROPOSER_BASE}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {PROPOSER_KEY}",
                 "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        body = json.loads(r.read())
    msg = body["choices"][0]["message"]
    tc  = (msg.get("tool_calls") or [{}])[0]
    raw = tc.get("function", {}).get("arguments", "{}")
    return json.loads(raw)


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--repo-dir", type=Path,
                   help="Working tree with recipe diff in place (uses git diff).")
    g.add_argument("--diff-file", type=Path,
                   help="Pre-saved unified diff (e.g. iter-NNN/results/<rid>/diff.patch).")
    p.add_argument("--repo-id",          required=True)
    p.add_argument("--java-version",     type=int, required=True)
    p.add_argument("--dependency-family", required=True)
    p.add_argument("--out", type=Path, default=None)
    args = p.parse_args()

    diff = git_diff(args.repo_dir) if args.repo_dir else args.diff_file.read_text()
    if not diff.strip():
        result = {
            "idiomatic_java21": 1, "antipattern_clearance": 1, "diff_coherence": 1,
            "overall": 1, "justification": "Empty diff — recipe applied no changes.",
            "empty_diff": True,
        }
    else:
        result = judge(args.repo_id, args.java_version, args.dependency_family, diff)
    out = args.out or (args.repo_dir / "qwen_judgement.json")
    out.write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

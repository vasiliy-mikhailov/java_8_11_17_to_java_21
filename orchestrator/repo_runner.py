"""Spin one Docker container per repo, run the recipe + scoring,
read back metrics.json. Concurrency is bounded by `--parallel`.

The Docker image is the one built from /harness/Dockerfile and is
expected to be tagged `j21-fitness:latest` (see Makefile).
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


log = logging.getLogger("repo_runner")


@dataclass
class RunRequest:
    repo_id: str
    url: str
    sha: str
    java_version: int
    build_tool: str        # "maven" | "gradle"


@dataclass
class RunResult:
    repo_id: str
    metrics: dict
    log_tail: str
    ok: bool


IMAGE_TAG = "j21-fitness:latest"


def _docker_run(req: RunRequest, recipe_name: str, recipe_yml_dir: Path,
                out_dir: Path, image: str = IMAGE_TAG, timeout_s: int = 1800) -> RunResult:
    """One container, mounted with the candidate rewrite.yml and an
    output directory. Returns the parsed metrics + a tail of the log."""
    out_dir.mkdir(parents=True, exist_ok=True)
    # Docker bind-mount paths MUST be absolute, otherwise the daemon
    # treats them as named volume identifiers and rejects them.
    abs_recipe_dir = Path(recipe_yml_dir).resolve()
    abs_out_dir = Path(out_dir).resolve()
    cmd = [
        "docker", "run", "--rm",
        "--network=host",
        "-v", f"{abs_recipe_dir}:/work/recipe:ro",
        "-v", f"{abs_out_dir}:/out",
        "-e", f"REPO_URL={req.url}",
        "-e", f"REPO_SHA={req.sha}",
        "-e", f"REPO_ID={req.repo_id}",
        "-e", f"JAVA_VERSION={req.java_version}",
        "-e", f"BUILD_TOOL={req.build_tool}",
        "-e", f"RECIPE_NAME={recipe_name}",
        "-e", "RECIPE_YML_PATH=/work/recipe/rewrite.yml",
        "-e", "OUT_DIR=/out",
        image,
    ]
    log.info("starting %s", req.repo_id)
    docker_stderr = b""
    docker_rc = None
    try:
        r = subprocess.run(cmd, check=False, timeout=timeout_s,
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        docker_stderr = r.stderr or b""
        docker_rc = r.returncode
    except subprocess.TimeoutExpired:
        log.warning("%s timed out after %ds", req.repo_id, timeout_s)
    if docker_rc not in (0, None):
        # Save docker's stderr to disk so failures aren't invisible.
        (out_dir / "docker.stderr").write_bytes(docker_stderr)
        log.warning("%s docker rc=%s; stderr: %s", req.repo_id, docker_rc,
                    docker_stderr.decode("utf-8", "replace")[:300].replace("\n", " | "))

    metrics_path = out_dir / "metrics.json"
    log_path = out_dir / "run.log"
    if metrics_path.exists():
        try:
            metrics = json.loads(metrics_path.read_text())
            ok = metrics.get("phase_reached") not in {None, "init", "clone"}
        except Exception:
            metrics = {"repo_id": req.repo_id, "phase_reached": "metrics-parse-failed"}
            ok = False
    else:
        metrics = {"repo_id": req.repo_id, "phase_reached": "no-metrics"}
        ok = False

    tail = ""
    if log_path.exists():
        try:
            tail = log_path.read_text().splitlines()[-60:]
            tail = "\n".join(tail)
        except Exception:
            tail = "<log unreadable>"

    return RunResult(repo_id=req.repo_id, metrics=metrics, log_tail=tail, ok=ok)


def evaluate_candidate(
    requests: Iterable[RunRequest],
    recipe_yml_text: str,
    recipe_name: str,
    results_root: Path,
    parallel: int = 4,
    iter_label: str = "iter",
) -> Path:
    """Materialise the candidate rewrite.yml on disk, then fan out one
    container per repo, capturing per-repo results under results_root."""
    iter_dir = results_root / iter_label
    if iter_dir.exists():
        shutil.rmtree(iter_dir)
    iter_dir.mkdir(parents=True, exist_ok=True)

    recipe_dir = iter_dir / "_recipe"
    recipe_dir.mkdir()
    (recipe_dir / "rewrite.yml").write_text(recipe_yml_text)

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = [
            pool.submit(_docker_run, r, recipe_name, recipe_dir, iter_dir / r.repo_id)
            for r in requests
        ]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            log.info("%s done ok=%s phase=%s", res.repo_id, res.ok,
                     res.metrics.get("phase_reached"))

    return iter_dir

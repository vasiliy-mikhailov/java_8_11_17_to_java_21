"""attempt_3 iter-0: apply iter-13 champion recipe to all 271 baselines.

Dataset shape: {cell_id, java_version, dep_family, repo_full_name, commit_sha,
                clone_url, build_tool, baseline_build_elapsed_s}.

Concurrency: BoundedSemaphore(16) — matches the verifier's working sweet spot.
Per-runner timeout: 1500s (same as attempt_2). Each docker run gets a --name so
that TimeoutExpired can kill the leaked container.
"""
import json, os, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
ITER = "attempt_3/iter-000"
DS = json.load(open(f"{HERE}/attempt_3/java21-migration-dataset.json"))

print(f"to run: {len(DS)}", flush=True)
sem = threading.BoundedSemaphore(16)
done = 0
lock = threading.Lock()

def run_one(e):
    global done
    env = os.environ.copy()
    env.update({
        "REPO_ID": e["cell_id"],
        "REPO_URL": e["clone_url"],
        "REPO_SHA": e.get("commit_sha") or "HEAD",
        "JAVA_VERSION": str(e["java_version"]),
        "BUILD_TOOL": e.get("build_tool", "maven"),
    })
    with sem:
        try:
            subprocess.run([f"{HERE}/{ITER}/run_one.sh"], env=env, timeout=1500,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            # Leak-safe: run_one.sh names each docker container so a stray container can be killed externally.
            pass
    with lock:
        done += 1
        print(f"  {done}/{len(DS)}: {e['cell_id']}", flush=True)

with ThreadPoolExecutor(max_workers=20) as ex:
    list(ex.map(run_one, DS))

print("all done")

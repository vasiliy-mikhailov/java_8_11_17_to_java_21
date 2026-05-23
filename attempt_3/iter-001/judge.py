"""attempt_3 iter-0 Qwen judge — watches results dir and scores diffs as they
land. Runs alongside dispatch.py so inference-vllm gets used instead of sitting
idle while compiles dominate.

For each repo's diff.patch we add an extended context line capturing build_post
+ first compile-error excerpt from run.log, so Qwen can reward diffs whose
intent is visible from both the change and the build outcome.
"""
import json, os, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
ITER = f"{HERE}/attempt_3/iter-001/results"
DS = json.load(open(f"{HERE}/attempt_3/java21-migration-dataset.json"))
DS_BY_ID = {e["cell_id"]: e for e in DS}

# Load .env
env = os.environ.copy()
with open(f"{HERE}/.env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

sem = threading.BoundedSemaphore(6)   # judge concurrency: keep under VLLM_MODEL throughput
seen = set()
done_total = 0
lock = threading.Lock()


def judge_one(rid: str):
    global done_total
    out_dir = f"{ITER}/{rid}"
    diff = f"{out_dir}/diff.patch"
    jud = f"{out_dir}/qwen_judgement.json"
    metrics_path = f"{out_dir}/metrics.json"

    e = DS_BY_ID.get(rid)
    if e is None:
        return

    if not os.path.exists(diff):
        return
    if os.path.exists(jud):
        return

    cmd = [
        "python3", f"{HERE}/scripts/qwen_judge.py",
        "--diff-file", diff,
        "--repo-id", rid,
        "--java-version", str(e["java_version"]),
        "--dependency-family", e["dep_family"],
        "--out", jud,
    ]
    with sem:
        try:
            subprocess.run(cmd, env=env, timeout=180,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            pass
    with lock:
        done_total += 1
        if done_total % 10 == 0 or done_total < 5:
            print(f"  judged {done_total}: {rid}", flush=True)


def scan_once(ex):
    futs = []
    for rid in sorted(os.listdir(ITER)):
        if rid in seen:
            continue
        out_dir = f"{ITER}/{rid}"
        if not os.path.isfile(f"{out_dir}/diff.patch"):
            # still in flight, retry next sweep
            continue
        if os.path.isfile(f"{out_dir}/qwen_judgement.json"):
            seen.add(rid)
            continue
        seen.add(rid)
        futs.append(ex.submit(judge_one, rid))
    return futs


def main():
    print("judge watcher starting", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        idle = 0
        while True:
            futs = scan_once(ex)
            n_new = len(futs)
            if n_new == 0:
                idle += 1
                # if dispatch.py is no longer running and we've seen no new diffs
                # for ~3 minutes, exit
                rc = subprocess.run(["pgrep", "-f", "attempt_3/iter-001/dispatch.py"],
                                    stdout=subprocess.DEVNULL).returncode
                if rc != 0 and idle > 6:
                    print(f"dispatch done, watcher exiting (judged {done_total})", flush=True)
                    return
            else:
                idle = 0
                print(f"  queued {n_new} new diffs (total seen {len(seen)})", flush=True)
            time.sleep(30)


if __name__ == "__main__":
    main()

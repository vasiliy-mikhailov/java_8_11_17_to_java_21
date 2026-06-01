"""Run Qwen judge on every iter-007 result's diff.patch in parallel."""
import json, os, subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
DS = json.load(open(f"{HERE}/attempt_2/java21-migration-dataset.json"))
ITER = f"{HERE}/attempt_2/iter-007/results"
print(f"dataset: {len(DS)}", flush=True)

# Load env from .env for PROPOSER_API_KEY
env = os.environ.copy()
with open(f"{HERE}/.env") as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

todo = []
for e in DS:
    out_dir = f"{ITER}/{e['id']}"
    diff = f"{out_dir}/diff.patch"
    jud = f"{out_dir}/qwen_judgement.json"
    if os.path.exists(jud):
        continue
    if not os.path.exists(diff):
        # Try alternate names
        for cand in ("recipe.patch", "rewrite.patch"):
            if os.path.exists(f"{out_dir}/{cand}"):
                diff = f"{out_dir}/{cand}"; break
    if not os.path.exists(diff):
        continue
    todo.append((e, diff))
print(f"to judge: {len(todo)}", flush=True)

done = 0
lock = threading.Lock()

def judge_one(args):
    global done
    e, diff = args
    out_dir = f"{ITER}/{e['id']}"
    cmd = ["python3", f"{HERE}/scripts/qwen_judge.py",
           "--diff-file", diff,
           "--repo-id", e["id"],
           "--java-version", str(e["java_version"]),
           "--dependency-family", e["dep_family"],
           "--out", f"{out_dir}/qwen_judgement.json"]
    try:
        subprocess.run(cmd, env=env, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        pass
    with lock:
        done += 1
        if done % 10 == 0:
            print(f"  judged {done}/{len(todo)}", flush=True)

with ThreadPoolExecutor(max_workers=6) as ex:
    list(ex.map(judge_one, todo))
print("all judged")

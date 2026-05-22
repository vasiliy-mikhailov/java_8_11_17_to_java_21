import json, os, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
DS = json.load(open(f"{HERE}/attempt_2/java21-migration-dataset.json"))
print(f"dataset entries: {len(DS)}", flush=True)

todo = []
for e in DS:
    out_dir = f"{HERE}/attempt_2/iter-005/results/{e['id']}"
    if os.path.exists(f"{out_dir}/metrics.json"):
        continue
    todo.append(e)
print(f"to run: {len(todo)}", flush=True)

sem = threading.BoundedSemaphore(6)
done = 0
lock = threading.Lock()

def run_one(e):
    global done
    env = os.environ.copy()
    env.update({
        "REPO_ID": e["id"],
        "REPO_URL": e["clone_url"],
        "REPO_SHA": e.get("commit_sha") or "HEAD",
        "JAVA_VERSION": str(e["java_version"]),
        "BUILD_TOOL": e.get("build_tool", "maven"),
    })
    with sem:
        try:
            subprocess.run(
                [f"{HERE}/attempt_2/iter-005/run_one.sh"],
                env=env, timeout=1500,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            pass
    with lock:
        done += 1
        if done % 5 == 0 or done == len(todo):
            print(f"  {done}/{len(todo)} repos done", flush=True)

with ThreadPoolExecutor(max_workers=12) as ex:
    list(ex.map(run_one, todo))
print("all done")

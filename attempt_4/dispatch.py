"""attempt_4 dispatcher: reads attempt_3 dataset and runs the staged pipeline per repo."""
import json, os, subprocess, threading, time
from concurrent.futures import ThreadPoolExecutor

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
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
            subprocess.run([f"{HERE}/attempt_4/run_one.sh"], env=env, timeout=2400,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            pass
    with lock:
        done += 1
        if done % 5 == 0 or done < 10:
            print(f"  {done}/{len(DS)}: {e['cell_id']}", flush=True)

with ThreadPoolExecutor(max_workers=20) as ex:
    list(ex.map(run_one, DS))

print("all done")

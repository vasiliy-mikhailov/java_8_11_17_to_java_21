import json, os, subprocess, threading
from concurrent.futures import ThreadPoolExecutor
HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
DS = json.load(open(f"{HERE}/attempt_2/java21-migration-dataset.json"))
TARGETS = ['hibernate-5__j11__3','jakarta-ee-javax__j11__2']
todo = [e for e in DS if e['id'] in TARGETS]
print(f'to run: {len(todo)}', flush=True)
sem = threading.BoundedSemaphore(2); done=0; lock=threading.Lock()
def run_one(e):
    global done
    env = os.environ.copy()
    env.update({'REPO_ID': e['id'],'REPO_URL': e['clone_url'],'REPO_SHA': e.get('commit_sha') or 'HEAD','JAVA_VERSION': str(e['java_version']),'BUILD_TOOL': e.get('build_tool','maven')})
    with sem:
        try: subprocess.run([f"{HERE}/attempt_2/iter-012/run_one.sh"], env=env, timeout=1500, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.TimeoutExpired: pass
    with lock:
        done += 1; print(f'  {done}/{len(todo)}: {e["id"]}', flush=True)
with ThreadPoolExecutor(max_workers=2) as ex: list(ex.map(run_one, todo))
print('all done')

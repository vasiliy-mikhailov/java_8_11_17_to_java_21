"""attempt-12 dataset generator: produce N valid baselines into dataset-shas.json.

Coordinated pool over the FULL shuffled dataset-repos.json: K workers claim repos in shuffle
order, bounded-search each for a compiling 8/11/17 baseline, append valid ones to a shared
ledger under flock, and the pool stops as soon as N are collected. So it draws from the entire
432-repo pool (never under-delivers if >=N repos yield) yet stops early (doesn't build all 432).
Per-repo sampling is keyed by (seed,repo), so the chosen sha is independent of which worker runs it.

Driver:  python3 sample_run.py --seed N [--n 100] [--workers 6] [--max-attempts 4]
Worker:  (same file, re-launched with --worker)
"""
import json, subprocess, os, sys, time, fcntl, random
from collections import Counter
A = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"
QF = "/tmp/sr_queue.txt"; RES = "/tmp/sr_results.jsonl"; CL = "/tmp/sr_claims"; LK = "/tmp/sr.lock"
NEXT = {8: 11, 11: 17, 17: 21}

def arg(n, d=None):
    for a in sys.argv:
        if a.startswith(n + "="):
            return a.split("=", 1)[1]
    return d

SEED = int(arg("--seed", "1")); N = int(arg("--n", "100")); WORKERS = int(arg("--workers", "6"))
MAXATT = int(arg("--max-attempts", "4")); SCAN = int(arg("--scan-cap", "150"))

def sh(c, to=300):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=to)
    except subprocess.TimeoutExpired:
        class R: returncode = 124; stdout = ""; stderr = ""
        return R()

def safe(r): return r.replace("/", "_")
def count_results(): return sum(1 for _ in open(RES)) if os.path.exists(RES) else 0

def search(repo):
    wd = "/tmp/srw_" + safe(repo)
    sh("rm -rf " + wd, 60); sh(f"git clone -q https://github.com/{repo} {wd}", 600)
    if not os.path.isdir(wd + "/.git"):
        return None
    commits = sh(f"git -C {wd} log --all --pretty=%H", 60).stdout.split()
    random.Random(f"{SEED}:{repo}").shuffle(commits)
    comp = scanned = 0; res = None
    for shav in commits:
        if scanned >= SCAN or comp >= MAXATT:
            break
        scanned += 1
        sh(f"git -C {wd} checkout -q {shav} 2>/dev/null", 60)
        if not os.path.isfile(wd + "/pom.xml"):
            continue
        jvout = sh("grep -rhoE '<(maven.compiler.release|java.version|maven.compiler.target|release|source)>[0-9]+' "
                   + wd + " --include=pom.xml 2>/dev/null | grep -oE '[0-9]+'").stdout.split()
        vs = [int(x) for x in jvout if x.isdigit() and int(x) in (8, 11, 17, 21)]
        jv = max(vs) if vs else None
        if jv not in NEXT:
            continue
        comp += 1
        rc = sh(f"export PATH=$HOME/bin:$PATH; cd {wd} && JDK={jv} mvn -q -B -ntp -DskipTests test-compile", 600).returncode
        if rc == 0:
            res = {"repo": repo, "sha": shav, "jv_from": jv, "jv_to": NEXT[jv], "attempts": comp}; break
    sh("rm -rf " + wd, 60)
    return res

def worker():
    QUEUE = open(QF).read().split()
    while True:
        lf = open(LK, "w"); fcntl.flock(lf, fcntl.LOCK_EX)
        try:
            if count_results() >= N:
                break
            repo = None
            for r in QUEUE:
                cd = os.path.join(CL, safe(r))
                if os.path.isdir(cd):
                    continue
                os.makedirs(cd); repo = r; break
        finally:
            fcntl.flock(lf, fcntl.LOCK_UN); lf.close()
        if repo is None:
            break
        res = search(repo)
        if res:
            lf = open(LK, "w"); fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                if count_results() < N:
                    open(RES, "a").write(json.dumps(res) + "\n")
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN); lf.close()
        print(("OK " + repo + " " + res["sha"][:8] + f" {res['jv_from']}->{res['jv_to']}") if res else ("MISS " + repo), flush=True)
    print("WORKER DONE", flush=True)

if "--worker" in sys.argv:
    worker(); sys.exit(0)

# ---- driver ----
repos = json.load(open(A + "/dataset-repos.json"))
random.Random(SEED).shuffle(repos)
open(QF, "w").write("\n".join(repos) + "\n")
sh(f"rm -rf {CL} {RES} {LK}", 30); os.makedirs(CL, exist_ok=True); open(RES, "w").close()
print(f"driver: full pool {len(repos)} repos, target {N}, {WORKERS} workers, seed {SEED}", flush=True)
procs = [subprocess.Popen(["python3", os.path.abspath(__file__), f"--seed={SEED}", f"--n={N}",
                           f"--max-attempts={MAXATT}", f"--scan-cap={SCAN}", "--worker"],
                          stdout=open(f"/tmp/sr_w{i}.out", "w"), stderr=subprocess.STDOUT) for i in range(WORKERS)]
for p in procs:
    p.wait()
qidx = {r: i for i, r in enumerate(repos)}
results = [json.loads(l) for l in open(RES)] if os.path.exists(RES) else []
results.sort(key=lambda e: qidx.get(e["repo"], 1 << 30))   # first-N in shuffle order
out = results[:N]
json.dump(out, open(A + "/dataset-shas.json", "w"), indent=1)
hops = Counter(f"{e['jv_from']}->{e['jv_to']}" for e in out)
print(f"dataset-shas.json: {len(out)}/{N} (seed {SEED}); hops={dict(hops)}; repos touched ~{len(os.listdir(CL))}", flush=True)
print("DONE", flush=True)

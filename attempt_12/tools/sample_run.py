"""attempt-12 dataset generator: produce N=100 valid baselines into dataset-shas.json.

Shuffles dataset-repos.json by --seed, takes a headroom slice, fans it out to parallel
sample_shas.py workers (each finds one compiling 8/11/17 baseline per repo), then assembles
the first N valid in shuffled order. Deterministic given --seed (per-repo sampling is keyed by
(seed,repo), so parallelism doesn't change which sha each repo yields).

Usage: python3 sample_run.py --seed N [--n 100] [--workers 6] [--max-attempts 4] [--headroom M]
"""
import json, subprocess, os, sys, random
from collections import Counter
A = "/home/vmihaylov/java_8_11_17_to_java_21/attempt_12"

def arg(n, d=None):
    for a in sys.argv:
        if a.startswith(n + "="):
            return a.split("=", 1)[1]
    return d

SEED = int(arg("--seed", "1"))
N = int(arg("--n", "100"))
WORKERS = int(arg("--workers", "6"))
MAXATT = int(arg("--max-attempts", "4"))
HEADROOM = int(arg("--headroom", str(int(N * 1.7))))  # process ~1.7x repos to net N valid

repos = json.load(open(A + "/dataset-repos.json"))
random.Random(SEED).shuffle(repos)
cand = repos[:HEADROOM]
chunks = [cand[i::WORKERS] for i in range(WORKERS)]
procs = []
for i, ch in enumerate(chunks):
    cf = f"/tmp/sr_chunk_{i}.txt"; open(cf, "w").write("\n".join(ch) + "\n")
    of = f"/tmp/sr_part_{i}.json"; open(of, "w").write("[]")
    p = subprocess.Popen(["python3", A + "/tools/sample_shas.py", f"--seed={SEED}",
                          f"--repos-file={cf}", f"--out={of}", f"--max-attempts={MAXATT}"],
                         stdout=open(f"/tmp/sr_w{i}.out", "w"), stderr=subprocess.STDOUT)
    procs.append((p, of))
print(f"launched {WORKERS} workers over {len(cand)} candidate repos (seed {SEED}, target {N})", flush=True)
for p, _ in procs:
    p.wait()

found = {}
for _, of in procs:
    try:
        for e in json.load(open(of)):
            found[e["repo"]] = e
    except Exception:
        pass
out = []
for repo in cand:                      # first-N in shuffled order = deterministic
    if repo in found:
        out.append(found[repo])
        if len(out) >= N:
            break
json.dump(out, open(A + "/dataset-shas.json", "w"), indent=1)
hops = Counter(f"{e['jv_from']}->{e['jv_to']}" for e in out)
print(f"dataset-shas.json: {len(out)}/{N} datapoints (seed {SEED}); hops={dict(hops)}", flush=True)
print("DONE", flush=True)

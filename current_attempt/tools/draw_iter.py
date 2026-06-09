"""Draw a fresh per-run iter-db by RANDOMLY sampling baselines from the year-structured
baseline store (the per-year dig output). No upfront fixed dataset — each round draws N
datapoints anew, so the eval is a moving target. <=1 sha per repo keeps the eval set
repo-diverse (independent datapoints); the store keeps the per-year/per-version multiples.

Usage: python3 draw_iter.py [--store FILE] [--n 100] [--seed R] [--out FILE]
Output: dataset-shas.json = [{repo, sha, jv_from, jv_to, year}] (the sweep's active corpus).
"""
import json, random, sys
A = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"
NEXT = {8: 11, 11: 17, 17: 21, 21: 25}

def arg(n, d=None):
    for a in sys.argv:
        if a.startswith(n + "="):
            return a.split("=", 1)[1]
    return d

STORE = arg("--store", "/home/vmihaylov/baselines_peryear.json.jsonl")
N = int(arg("--n", "100"))
SEED = int(arg("--seed", "0"))
OUT = arg("--out", A + "/dataset-shas.json")

# load the store (jsonl, append-only; tolerate partial last line)
baselines = []
for line in open(STORE):
    line = line.strip()
    if not line:
        continue
    try:
        b = json.loads(line)
        if b.get("jv_from") in NEXT:
            baselines.append(b)
    except Exception:
        pass

# group by repo; one random baseline (year/sha) per repo -> repo-diverse pool
by_repo = {}
for b in baselines:
    by_repo.setdefault(b["repo"], []).append(b)
rng = random.Random(SEED)
repos = list(by_repo)
rng.shuffle(repos)

iter_db = []
for repo in repos[:N]:
    b = rng.choice(by_repo[repo])
    iter_db.append({"repo": b["repo"], "sha": b["sha"], "jv_from": b["jv_from"],
                    "jv_to": NEXT[b["jv_from"]], "year": b.get("year")})
json.dump(iter_db, open(OUT, "w"), indent=1)

from collections import Counter
hops = Counter(f"{e['jv_from']}->{e['jv_to']}" for e in iter_db)
print(f"iter: {len(iter_db)} datapoints (<=1/repo) drawn random from {len(by_repo)} repos "
      f"/ {len(baselines)} baselines in store; seed {SEED}; hops {dict(hops)} -> {OUT}")

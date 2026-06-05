#!/usr/bin/env python3
"""Drive opencode (Qwen FP8) over N dataset examples inside bump-portability:latest, one
container per repo, K concurrent. Each container runs opencode_drive_one.sh (fetch -> baseline
-> opencode bump via the skill -> compile+test under jv_to -> conservation). Collects results
and prints a PASS rate.  Usage: OC_KEY=... python3 opencode_sweep.py [N=100] [K=6] [offset=0]
"""
import os, sys, json, subprocess, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter

BASE = "/home/vmihaylov/java_8_11_17_to_java_21"
ACTIVE = f"{BASE}/current_attempt"
SKILL = f"{ACTIVE}/.agents/skills/bump-java-version"
CFG = f"{ACTIVE}/portability"
DRIVE = "/home/vmihaylov/opencode_drive_one.sh"
OUT = "/home/vmihaylov/opencode_sweep_out"
M2 = "/home/vmihaylov/.m2-fitness"
SETTINGS = "/home/vmihaylov/maven-config/settings.xml"
IMAGE = "bump-opencode-sweep:latest"
OC_KEY = os.environ["OC_KEY"]

N = int(sys.argv[1]) if len(sys.argv) > 1 else 100
K = int(sys.argv[2]) if len(sys.argv) > 2 else 6
OFF = int(sys.argv[3]) if len(sys.argv) > 3 else 0

ds = json.load(open(f"{ACTIVE}/dataset-shas.json"))
# balanced-by-hop sample so the rate isn't dominated by one hop
from collections import defaultdict
byhop = defaultdict(list)
for e in ds:
    byhop[f"{e['jv_from']}->{e['jv_to']}"].append(e)
hops = sorted(byhop)
per = N // len(hops)
examples = []
for h in hops:
    examples += byhop[h][OFF:OFF + per]
examples = examples[:N]
os.makedirs(OUT, exist_ok=True)
print(f"selected {len(examples)} examples: " +
      ", ".join(f"{h}:{sum(1 for e in examples if f'''{e['jv_from']}->{e['jv_to']}''' == h)}" for h in hops), flush=True)


def run_one(e):
    repo, sha = e["repo"], e["sha"]
    frm, to = e["jv_from"], e["jv_to"]
    slug = repo.replace("/", "_") + "_" + sha[:8]
    cname = "oc_" + uuid.uuid4().hex[:10]
    cmd = ["docker", "run", "--rm", "--name", cname, "--network", "mvn-cache",
           "-e", f"OC_KEY={OC_KEY}",
           "-v", f"{SKILL}:/skill:ro", "-v", f"{CFG}:/cfg:ro", "-v", f"{OUT}:/out",
           "-v", f"{M2}:/root/.m2", "-v", f"{SETTINGS}:/root/.m2/settings.xml:ro",
           "-v", f"{DRIVE}:/drive.sh:ro",
           "--entrypoint", "bash", IMAGE, "/drive.sh", repo, sha, str(frm), str(to), slug]
    try:
        subprocess.run(cmd, capture_output=True, timeout=3300)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", cname], capture_output=True)
        subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
    rp = f"{OUT}/{slug}/result.json"
    if os.path.exists(rp):
        try:
            return json.load(open(rp))
        except Exception:
            pass
    return {"slug": slug, "repo": repo, "hop": f"{frm}->{to}", "verdict": "NO_RESULT"}


results = []
with ThreadPoolExecutor(max_workers=K) as pool:
    futs = {pool.submit(run_one, e): e for e in examples}
    for i, f in enumerate(as_completed(futs), 1):
        r = f.result()
        results.append(r)
        print(f"[{i}/{len(examples)}] {r.get('repo')} {r.get('hop','')} -> {r.get('verdict')} "
              f"(pre={r.get('pre_pass')}, post={r.get('post_pass')}, lost={r.get('lost')})", flush=True)

json.dump(results, open(f"{OUT}/_summary.json", "w"), indent=1)
c = Counter(r.get("verdict") for r in results)
scored = sum(v for k, v in c.items() if k in ("PASS", "FAIL_build_post", "FAIL_test_conservation"))
npass = c.get("PASS", 0)
print("\n=== TALLY ===", dict(c))
print(f"PASS {npass}/{scored} = {100*npass/max(1,scored):.0f}% "
      f"(excludes NO_BASELINE/NO_MVNW/FETCH_FAIL/NO_RESULT)")
print("SWEEP_DONE")

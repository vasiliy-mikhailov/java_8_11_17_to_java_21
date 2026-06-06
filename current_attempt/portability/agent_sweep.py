#!/usr/bin/env python3
"""Unified 3-agent sweep. One image (bump-allagents-sweep) + one driver (agent_drive_one.sh);
the AGENT is the only variable. Usage: OC_KEY=... python3 agent_sweep.py <opencode|kilo|openhands> [N=40] [K=3] [OFF=0]
"""
import os, sys, json, subprocess, uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict

AGENT = sys.argv[1]
N = int(sys.argv[2]) if len(sys.argv) > 2 else 40
K = int(sys.argv[3]) if len(sys.argv) > 3 else 3
OFF = int(sys.argv[4]) if len(sys.argv) > 4 else 0
BASE = "/home/vmihaylov/java_8_11_17_to_java_21"
ACTIVE = f"{BASE}/current_attempt"
SKILL = f"{ACTIVE}/.agents/skills/bump-java-version"
CFG = f"{ACTIVE}/portability"
DRIVE = "/home/vmihaylov/agent_drive_one.sh"
OHRUN = "/home/vmihaylov/oh_run.py"
OUT = f"/home/vmihaylov/sweep3_{AGENT}" + os.environ.get("OUT_SUFFIX", "")
M2 = "/home/vmihaylov/.m2-fitness"
SETTINGS = "/home/vmihaylov/maven-config/settings.xml"
IMAGE = "bump-allagents-sweep:latest"
OC_KEY = os.environ["OC_KEY"]

ds = json.load(open(os.environ.get("DATASET_FILE", f"{ACTIVE}/dataset-shas.json")))
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
print(f"[{AGENT}] {len(examples)} examples: " +
      ", ".join(f"{h}:{sum(1 for e in examples if f'''{e['jv_from']}->{e['jv_to']}''' == h)}" for h in hops), flush=True)


def run_one(e):
    repo, sha, frm, to = e["repo"], e["sha"], e["jv_from"], e["jv_to"]
    slug = repo.replace("/", "_") + "_" + sha[:8]
    cname = "a3_" + uuid.uuid4().hex[:10]
    cmd = ["docker", "run", "--rm", "--name", cname, "--network", "mvn-cache", "-e", f"OC_KEY={OC_KEY}",
           "-v", f"{SKILL}:/skill:ro", "-v", f"{CFG}:/cfg:ro", "-v", f"{OUT}:/out",
           "-v", f"{M2}:/root/.m2", "-v", f"{SETTINGS}:/root/.m2/settings.xml:ro",
           "-v", f"{DRIVE}:/drive.sh:ro", "-v", f"{OHRUN}:/oh_run.py:ro",
           "--entrypoint", "bash", IMAGE, "/drive.sh", repo, sha, str(frm), str(to), slug, AGENT]
    try:
        subprocess.run(cmd, capture_output=True, timeout=3300)
    except subprocess.TimeoutExpired:
        subprocess.run(["docker", "kill", cname], capture_output=True)
        subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
    rp = f"{OUT}/{slug}/result.json"
    return json.load(open(rp)) if os.path.exists(rp) else {"slug": slug, "repo": repo, "hop": f"{frm}->{to}", "verdict": "NO_RESULT"}


res = []
with ThreadPoolExecutor(max_workers=K) as pool:
    for i, f in enumerate(as_completed([pool.submit(run_one, e) for e in examples]), 1):
        r = f.result()
        res.append(r)
        print(f"[{AGENT} {i}/{len(examples)}] {r.get('repo')} {r.get('hop','')} -> {r.get('verdict')} "
              f"(pre={r.get('pre_pass')}, post={r.get('post_pass')})", flush=True)
json.dump(res, open(f"{OUT}/_summary.json", "w"), indent=1)
c = Counter(r.get("verdict") for r in res)
scored = sum(v for k, v in c.items() if k in ("PASS", "FAIL_build_post", "FAIL_test_conservation"))
print(f"\n[{AGENT}] TALLY", dict(c))
print(f"[{AGENT}] PASS {c.get('PASS',0)}/{scored} = {100*c.get('PASS',0)/max(1,scored):.0f}%")
print(f"SWEEP3_DONE_{AGENT}")

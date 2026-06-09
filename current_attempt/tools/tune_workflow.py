#!/usr/bin/env python3
"""Tune workflow — the rung-1/rung-2 optimization loop as one repeatable command.

  tune_workflow.py status            current rung-2 rate by hop + failure clusters (no run)
  tune_workflow.py sweep  [workers]  CLEAN full rung-2 sweep over dataset-shas.json, then measure+triage
  tune_workflow.py rerun  [workers]  CLEAN re-run of the CURRENT failures only, then measure+triage

Each run-phase is self-cleaning so every iteration is a trustworthy before/after:
  1. reap orphan j21-fitness build containers + stale oh_drive/corpus_sweep procs (the
     resource contamination that made earlier numbers noisy),
  2. clear the relevant per_repo_iter trajectories (all for `sweep`, just the failures for `rerun`),
  3. run corpus_sweep (OH+Qwen, rung 2) to completion — resumable, reaps each workdir,
  4. print rate-by-hop and re-run the rung-1 cluster triage on the residual failures.

The deterministic FIX step between iterations is Claude's (convert the top cluster to a
bump-script/recipe step); this tool automates everything around it. Launch a run-phase with
nohup since it blocks for the full sweep:  nohup tune_workflow.py rerun 6 > /tmp/wf.log 2>&1 &
"""
import json, os, re, sys, time, shutil, subprocess, collections

BASE = "/home/vmihaylov/java_8_11_17_to_java_21"
A = BASE + "/current_attempt"
TOOLS = A + "/tools"
SWEEP = TOOLS + "/corpus_sweep.py"
TRIAGE = TOOLS + "/rung1_triage.py"
RES = A + "/sweep_results.json"
OUT = A + "/per_repo_iter"
DS = A + "/dataset-shas.json"


def sh(c, to=180):
    return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=to)


def hops():
    return {(x["repo"].replace("/", "_") + "_" + x["sha"][:12]): "%d->%d" % (x["jv_from"], x["jv_to"])
            for x in json.load(open(DS))}


def is_fail(v):
    return isinstance(v, str) and (v.startswith("FAIL") or v == "TIMEOUT" or v.startswith("rc="))


def reap():
    print("[workflow] reaping orphan containers + stale procs ...", flush=True)
    sh("docker ps -q --filter ancestor=j21-fitness:latest | xargs -r docker kill", to=120)
    for pat in ("[o]h_drive", "[c]orpus_sweep"):
        sh("ps aux | grep '%s' | awk '{print $2}' | xargs -r kill -9" % pat, to=60)
    sh("rm -rf /tmp/oh_drive_* /tmp/vg_*", to=120)
    time.sleep(2)


def measure(tag=""):
    res = json.load(open(RES)) if os.path.exists(RES) else {}
    h = hops()
    byhop = collections.defaultdict(list)
    for slug, v in res.items():
        if isinstance(v, str):
            byhop[h.get(slug, "?")].append(v)
    allv = [v for vs in byhop.values() for v in vs]
    pa = sum(v.startswith("PASS") for v in allv)
    print("\n=== rate by hop %s ===" % tag, flush=True)
    print("  OVERALL  %d/%d = %d%% PASS" % (pa, len(allv), 100 * pa // max(1, len(allv))), flush=True)
    for hop in sorted(byhop):
        vs = byhop[hop]
        p = sum(v.startswith("PASS") for v in vs)
        print("  %-7s  %d/%d = %d%%   %s" % (hop, p, len(vs), 100 * p // max(1, len(vs)), dict(collections.Counter(vs))), flush=True)


def triage():
    if os.path.exists(TRIAGE):
        print(sh("python3 %s %s" % (TRIAGE, RES), to=180).stdout, flush=True)


def run_sweep(workers):
    print("[workflow] launching corpus_sweep (rung 2, OH+Qwen) %d workers — blocks to completion" % workers, flush=True)
    p = subprocess.Popen(["python3", SWEEP, str(workers)],
                         stdout=open("/tmp/workflow_sweep.log", "w"), stderr=subprocess.STDOUT)
    p.wait()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6

    if cmd == "status":
        measure("(current)")
        triage()
        return

    reap()
    if cmd == "sweep":
        if os.path.isdir(OUT):
            shutil.move(OUT, OUT + "_bak_" + str(int(time.time())))
        os.makedirs(OUT, exist_ok=True)
        if os.path.exists(RES):
            os.remove(RES)
        print("[workflow] cleared ALL trajectories -> full clean sweep", flush=True)
    elif cmd == "rerun":
        res = json.load(open(RES)) if os.path.exists(RES) else {}
        n = 0
        for slug, v in res.items():
            if is_fail(v):
                d = OUT + "/" + slug
                if os.path.isdir(d):
                    shutil.rmtree(d)
                    n += 1
        print("[workflow] cleared %d failure trajectories -> clean re-run of failures" % n, flush=True)
    else:
        print("usage: tune_workflow.py status|sweep|rerun [workers]")
        return

    t0 = time.time()
    run_sweep(workers)
    print("\n[workflow] sweep complete in %dm" % ((time.time() - t0) / 60), flush=True)
    measure("(after %s)" % cmd)
    triage()


if __name__ == "__main__":
    main()

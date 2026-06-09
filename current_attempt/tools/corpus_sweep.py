#!/usr/bin/env python3
"""Full active-attempt sweep: oh_drive (OH+Qwen, the production rung) over every datapoint
in current_attempt/dataset-shas.json. K workers, skip-if-done (trajectory exists), reap each
oh_drive workdir after its run (per-run reap discipline), tally corpus PASS rate.
Usage: corpus_sweep.py [workers]"""
import json, os, re, subprocess, sys, time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "/home/vmihaylov/java_8_11_17_to_java_21"
ACTIVE = f"{BASE}/current_attempt"
OH = f"{ACTIVE}/tools/oh_drive.py"
DS = f"{ACTIVE}/dataset-shas.json"
OUT = f"{ACTIVE}/per_repo_iter"
RES = f"{ACTIVE}/sweep_results.json"
WORKERS = int(sys.argv[1]) if len(sys.argv) > 1 else 6


def slug_of(d):
    return d["repo"].replace("/", "_") + "_" + d["sha"][:12]


def reap(wd):
    """Reap oh_drive's root-owned /tmp workdir via a root container (it writes root files
    during docker_phase and keeps the dir; a user rm would leak it)."""
    if wd and wd.startswith("/tmp/") and len(os.path.basename(wd)) > 5:
        subprocess.run(["docker", "run", "--rm", "-v", "/tmp:/host", "--entrypoint", "sh",
                        "j21-fitness:latest", "-c", "rm -rf /host/" + os.path.basename(wd)],
                       capture_output=True, timeout=120)


def run_one(d):
    slug = slug_of(d)
    traj = f"{OUT}/{slug}/trajectory.json"
    if os.path.exists(traj):
        try:
            return slug, json.load(open(traj)).get("verdict", "cached"), 0, True
        except Exception:
            return slug, "cached", 0, True
    env = dict(os.environ)
    env["PATH"] = "/home/vmihaylov/bin:" + env.get("PATH", "")
    t0 = time.time()
    try:
        p = subprocess.run(["python3", OH, slug], env=env, capture_output=True, text=True, timeout=2400)
        out = p.stdout or ""
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout.decode(errors="replace") if e.stdout else "")
        m = re.search(r"workdir.*?: (\S+)", out)
        reap(m.group(1) if m else None)
        return slug, "TIMEOUT", round(time.time() - t0), False
    m = re.search(r"workdir kept for inspection: (\S+)", out)
    reap(m.group(1) if m else None)
    try:
        v = json.load(open(traj)).get("verdict", "no-traj")
    except Exception:
        v = "rc=%d %s" % (p.returncode, (p.stderr or "").strip().replace("\n", " ")[-160:])
    return slug, v, round(time.time() - t0), False


def main():
    ds = json.load(open(DS))
    n = len(ds)
    print("=== full sweep: %d datapoints | %d workers | oh_drive (OH+Qwen) ===" % (n, WORKERS), flush=True)
    results = {}
    if os.path.exists(RES):
        try:
            results = json.load(open(RES))
        except Exception:
            pass
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(run_one, d) for d in ds]
        for fut in as_completed(futs):
            slug, v, wall, cached = fut.result()
            results[slug] = v
            done += 1
            json.dump(results, open(RES, "w"), indent=1)
            print("[%d/%d] %s: %s (%s)" % (done, n, slug, v, "cached" if cached else "%ds" % wall), flush=True)
    tally = Counter((v if isinstance(v, str) else str(v)).split(":")[0] for v in results.values())
    passes = sum(1 for v in results.values() if isinstance(v, str) and v.startswith("PASS"))
    print("=== DONE. TALLY: %s ===" % dict(tally), flush=True)
    print("=== corpus PASS rate: %d/%d = %.1f%% ===" % (passes, len(results), 100.0 * passes / max(1, len(results))), flush=True)


if __name__ == "__main__":
    main()

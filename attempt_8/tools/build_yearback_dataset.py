"""attempt_8 dataset builder — per ff #2 contract.

For each (repo, jv_from→jv_to=21) stage in the existing lineage dataset, find a
NEW sha_from that:
  1. Is roughly one year BEFORE the version-bump commit (sha_to)
  2. Compiles cleanly under jv_from
  3. Has a unit-test pass-rate ≥ 0.7 (defaults configurable)
  4. Has at least 1 passing test (so item 8's test-conservation isn't degenerate)

We probe candidates spiralling outward from the 365-day target inside a
configurable window (default ±180 days), one mvn compile + mvn test per probe,
accepting the first candidate that meets the bar.

Output: attempt_8/dataset_yearback.json — JSON list of:
  {repo, sha_from, sha_to, jv_from, jv_to, days_back_actual,
   pre_pass_count, pre_fail_count, pass_rate, probes_tried}

Skipped stages are written to attempt_8/dataset_yearback_skipped.json with reason.

Usage:
  build_yearback_dataset.py [--input <lineage.json>] [--output attempt_8/...]
                            [--target-days 365] [--window-days 180]
                            [--min-pass-rate 0.7] [--max-probes 5]
                            [--workers 6] [--limit N]
                            [--filter-slug 'pattern*']
"""
import os, sys, json, time, argparse, subprocess, tempfile, shutil, uuid, threading
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Reuse machinery from attempt_7
sys.path.insert(0, "/home/vmihaylov/java_8_11_17_to_java_21/attempt_7/tools")
from run_sequenced_java import (
    docker_phase, shallow_fetch, WORK, BASE, ATTEMPT7,
)
from test_conservation import parse_surefire_dir, clear_surefire

ATTEMPT8 = f"{BASE}/attempt_8"
DEFAULT_INPUT = f"{BASE}/attempt_5/lineage_dataset_v4_final.json"
DEFAULT_OUTPUT = f"{ATTEMPT8}/dataset_yearback.json"
DEFAULT_SKIPPED = f"{ATTEMPT8}/dataset_yearback_skipped.json"
DEFAULT_PERSTAGE_DIR = f"{ATTEMPT8}/yearback_probes"

os.makedirs(ATTEMPT8, exist_ok=True)
os.makedirs(DEFAULT_PERSTAGE_DIR, exist_ok=True)


def git_in(work, *args, timeout=120):
    r = subprocess.run(["git", "-C", work] + list(args), capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode(errors="replace"), r.stderr.decode(errors="replace")


def cache_path(repo):
    return f"/var/cache/git-mirrors/{repo}.git"


def have_cache(repo):
    p = cache_path(repo)
    return os.path.isdir(p) and os.path.isfile(os.path.join(p, "HEAD"))


def commit_date_iso(repo_or_work, sha):
    """Read commit date. Works on either a clone path OR the bare cache.
    The cache is partial-clone (blob:none) so blobs are missing, but commit
    metadata is present — `git show -s` works fine without lazy-fetching."""
    arg = repo_or_work if os.path.isdir(repo_or_work) else cache_path(repo_or_work)
    r = subprocess.run(["git", "-C", arg, "show", "-s", "--format=%cI", sha],
                       capture_output=True, timeout=15)
    if r.returncode != 0: return None
    try: return datetime.fromisoformat(r.stdout.decode().strip().replace("Z", "+00:00"))
    except Exception: return None


def candidates_around(repo, target_dt, window_days, max_candidates=8):
    """Return commit shas around target_dt from the local mirror cache (no network)."""
    if not target_dt: return []
    import datetime as _dt
    iso_lo = (target_dt - _dt.timedelta(days=window_days)).isoformat()
    iso_hi = (target_dt + _dt.timedelta(days=window_days)).isoformat()
    r = subprocess.run(
        ["git", "-C", cache_path(repo), "log", "--first-parent", "--format=%H %cI",
         f"--since={iso_lo}", f"--until={iso_hi}", "HEAD"],
        capture_output=True, timeout=60,
    )
    if r.returncode != 0: return []
    rows = []
    for ln in r.stdout.decode(errors="replace").splitlines():
        parts = ln.split(" ", 1)
        if len(parts) != 2: continue
        sha, iso = parts
        try: d = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except Exception: continue
        rows.append((sha, d, abs((d - target_dt).total_seconds())))
    rows.sort(key=lambda r: r[2])
    return rows[:max_candidates]


def probe_candidate(repo, sha, jv_from, work_dir=None, timeout_each=900):
    """Checkout candidate, mvn compile + mvn test under jv_from, return (compile_ok, p_pass, p_fail)."""
    work = tempfile.mkdtemp(prefix="yb_probe_", dir=WORK)
    rdir = tempfile.mkdtemp(prefix="yb_r_", dir=WORK)
    logs = tempfile.mkdtemp(prefix="yb_l_", dir=WORK)
    try:
        if not shallow_fetch(repo, sha, work): return (False, 0, 0, "fetch_failed")
        # compile
        rc_c, _ = docker_phase(work, rdir, logs, "build_pre", jv_from, timeout=timeout_each)
        if rc_c != 0: return (False, 0, 0, f"compile_rc={rc_c}")
        # test_pre  (the entry script supports this phase)
        clear_surefire(work)
        rc_t, _ = docker_phase(work, rdir, logs, "test_pre", jv_from, timeout=timeout_each)
        passed, failed = parse_surefire_dir(work)
        return (True, len(passed), len(failed), f"test_rc={rc_t}")
    finally:
        for d in (work, rdir, logs):
            shutil.rmtree(d, ignore_errors=True)


def best_sha_from(stage, target_days, window_days, min_pass_rate, max_probes):
    """For one stage: read commit metadata from cache, then shallow_fetch each probe (1 SHA)."""
    repo = stage["repo"]
    sha_bump = stage["sha_from"]
    jv_from = stage["jv_from"]
    slug = f"{repo.replace('/', '_')}__J{jv_from}toJ{stage['jv_to']}"
    probe_log = f"{DEFAULT_PERSTAGE_DIR}/{slug}.json"
    if os.path.exists(probe_log):
        return json.load(open(probe_log))

    record = {"slug": slug, "stage": stage, "probes": [], "selected": None, "skipped_reason": None}

    if not have_cache(repo):
        record["skipped_reason"] = "cache_miss"
        json.dump(record, open(probe_log, "w"), indent=2)
        return record

    bump_dt = commit_date_iso(repo, sha_bump)
    if not bump_dt:
        record["skipped_reason"] = "bump_date_unknown"
        json.dump(record, open(probe_log, "w"), indent=2)
        return record
    import datetime as _dt
    target_dt = bump_dt - _dt.timedelta(days=target_days)
    record["sha_bump"] = sha_bump
    record["sha_bump_dt"] = bump_dt.isoformat()
    record["target_dt"] = target_dt.isoformat()

    cands = candidates_around(repo, target_dt, window_days, max_candidates=max_probes * 2)
    if not cands:
        record["skipped_reason"] = "no_candidates_in_window"
        json.dump(record, open(probe_log, "w"), indent=2)
        return record

    for sha, dt, _delta in cands[:max_probes]:
        # probe_candidate uses shallow_fetch internally — 1 small SHA pull
        work = tempfile.mkdtemp(prefix="yb_probe_", dir=WORK)
        try:
            compile_ok, p_pass, p_fail, note = probe_candidate(repo, sha, jv_from, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        days_back = (bump_dt - dt).days
        pass_rate = p_pass / max(1, (p_pass + p_fail))
        probe = {
            "sha": sha, "dt": dt.isoformat(), "days_back": days_back,
            "compile_ok": compile_ok, "pass": p_pass, "fail": p_fail,
            "pass_rate": round(pass_rate, 3), "note": note,
        }
        record["probes"].append(probe)
        json.dump(record, open(probe_log, "w"), indent=2)
        if compile_ok and p_pass >= 1 and pass_rate >= min_pass_rate:
            record["selected"] = {
                "repo": repo, "sha_from": sha,
                "sha_to": stage.get("sha_to"),
                "jv_from": jv_from, "jv_to": stage["jv_to"],
                "days_back_actual": days_back,
                "pre_pass_count": p_pass, "pre_fail_count": p_fail,
                "pass_rate": round(pass_rate, 3),
                "probes_tried": len(record["probes"]),
            }
            json.dump(record, open(probe_log, "w"), indent=2)
            return record

    record["skipped_reason"] = "no_candidate_met_bar"
    json.dump(record, open(probe_log, "w"), indent=2)
    return record


def gather_j21_stages(corpus):
    """Pull every adjacent (jv_from -> 21) stage out of the corpus."""
    stages = []
    for e in corpus:
        vl = sorted(e["verified_lineage"], key=lambda s: s["java_version"])
        for i in range(len(vl) - 1):
            if vl[i + 1]["java_version"] != 21: continue
            stages.append({
                "repo": e["repo_full_name"],
                "sha_from": vl[i]["commit_sha"],   # the existing one — used as a "near" anchor; we'll walk back from sha_to's parent
                "sha_to": vl[i + 1]["commit_sha"],
                "jv_from": vl[i]["java_version"],
                "jv_to": 21,
            })
    return stages


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_INPUT)
    ap.add_argument("--output", default=DEFAULT_OUTPUT)
    ap.add_argument("--skipped", default=DEFAULT_SKIPPED)
    ap.add_argument("--target-days", type=int, default=365)
    ap.add_argument("--window-days", type=int, default=180)
    ap.add_argument("--min-pass-rate", type=float, default=0.7)
    ap.add_argument("--max-probes", type=int, default=5)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--filter-slug", default="")
    args = ap.parse_args()

    corpus = json.load(open(args.input))
    stages = gather_j21_stages(corpus)
    if args.filter_slug:
        import fnmatch
        stages = [s for s in stages if fnmatch.fnmatchcase(
            f"{s['repo'].replace('/', '_')}__J{s['jv_from']}toJ{s['jv_to']}",
            args.filter_slug)]
    if args.limit: stages = stages[:args.limit]
    print(f"=== {len(stages)} J21-target stages to probe ===", flush=True)

    done = [0]; lock = threading.Lock()
    def go(s):
        slug = f"{s['repo'].replace('/', '_')}__J{s['jv_from']}toJ{s['jv_to']}"
        try:
            rec = best_sha_from(s, args.target_days, args.window_days, args.min_pass_rate, args.max_probes)
        except Exception as e:
            rec = {"slug": slug, "stage": s, "skipped_reason": f"EXC:{type(e).__name__}:{e}"}
        with lock:
            done[0] += 1
            sel = rec.get("selected")
            if sel:
                print(f"  [{done[0]:3d}/{len(stages)}] {slug}: SELECTED days_back={sel['days_back_actual']} pre={sel['pre_pass_count']}p/{sel['pre_fail_count']}f rate={sel['pass_rate']}", flush=True)
            else:
                print(f"  [{done[0]:3d}/{len(stages)}] {slug}: SKIPPED reason={rec.get('skipped_reason')}", flush=True)
        return rec

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        all_recs = list(ex.map(go, stages))

    selected = [r["selected"] for r in all_recs if r.get("selected")]
    skipped = [{"slug": r["slug"], "reason": r.get("skipped_reason"),
                "probes": r.get("probes", [])} for r in all_recs if not r.get("selected")]
    json.dump(selected, open(args.output, "w"), indent=2)
    json.dump(skipped, open(args.skipped, "w"), indent=2)
    print(f"\n=== SUMMARY ===")
    print(f"  selected: {len(selected)}/{len(stages)} ({100*len(selected)/max(1,len(stages)):.1f}%)")
    print(f"  skipped:  {len(skipped)}")
    print(f"  saved:    {args.output}")


if __name__ == "__main__":
    main()

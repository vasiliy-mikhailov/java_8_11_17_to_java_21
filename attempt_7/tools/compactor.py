"""ff #7 compactor — telemetry capture + Qwen-driven bottleneck digest.

Two modes:
  capture   sample host + iterator + container state once and append to
            attempt_7/telemetry/raw-YYYY-MM-DD.jsonl
  digest    read recent raw samples (default last 60 min), build a snapshot,
            invoke Qwen (thinking mode) to identify rate-limiters + anomalies,
            append the result to attempt_7/telemetry/digest-YYYY-MM-DD.jsonl
            ONLY if the digest differs materially from the previous one
            (frog's-eyes behavior).
  loop      run capture every --capture-s (default 60) and digest every
            --digest-s (default 600); designed to be nohup'd.
  show      print the latest digest entry to stdout.

Outputs are flat jsonl so an operator can `tail -f` them.

Usage:
  compactor.py capture
  compactor.py digest [--window-min 60] [--force]
  compactor.py loop [--capture-s 60] [--digest-s 600]
  compactor.py show
"""
import os, sys, json, time, argparse, subprocess, urllib.request, urllib.error, hashlib
from datetime import datetime

BASE = "/home/vmihaylov/java_8_11_17_to_java_21"
TELEMETRY_DIR = f"{BASE}/attempt_7/telemetry"
os.makedirs(TELEMETRY_DIR, exist_ok=True)
ROUND_ROBIN_LOG = "/tmp/round_robin.log"
SEQUENCED_LOG = "/tmp/seqj_full.log"
ITER_TRAJ_DIR = os.environ.get("ITER_TRAJ_DIR") or f"{BASE}/attempt_8/per_repo_iter"


def load_env(p=f"{BASE}/.env"):
    env = {}
    if os.path.exists(p):
        for ln in open(p):
            ln = ln.strip()
            if "=" in ln and not ln.startswith("#"):
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip()
    return env


ENV = load_env()
# Per ff #5: compactor (high-frequency, structured-output) gets its own endpoint when
# available; falls back to the main PROPOSER_* values if OPENHANDS_CONTEXT_COMPACTOR_* aren't set.
PROPOSER_URL = ENV.get("OPENHANDS_CONTEXT_COMPACTOR_BASE_URL",
                   ENV.get("PROPOSER_BASE_URL", "https://inference.mikhailov.tech/v1")).rstrip("/")
PROPOSER_KEY = ENV.get("OPENHANDS_CONTEXT_COMPACTOR_API_KEY", ENV.get("PROPOSER_API_KEY", ""))
PROPOSER_MODEL = ENV.get("OPENHANDS_CONTEXT_COMPACTOR_MODEL", ENV.get("PROPOSER_MODEL", "qwen3.6-27b-fp8"))


def sh_int(cmd, timeout=10, default=0):
    s = sh(cmd, timeout=timeout)
    try:
        return int(s.strip().split("\n")[0])
    except Exception:
        return default


def sh(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout, shell=True)
        return r.stdout.decode(errors="replace").strip()
    except Exception as e:
        return f"<err: {type(e).__name__}: {e}>"


VECTOR_HOST_METRICS = "/var/log/observe/host_metrics.jsonl"
VECTOR_DOCKER = "/var/log/observe/docker.jsonl"
VECTOR_APP_LOGS = "/var/log/observe/app_logs.jsonl"


def _tail_jsonl(path, since_ts, max_lines=20000):
    """Yield JSONL rows from the file whose timestamp is >= since_ts.
    We tail the last max_lines of the file (cheap), parse, and filter."""
    if not os.path.exists(path): return
    try:
        r = subprocess.run(["tail", "-n", str(max_lines), path],
                           capture_output=True, timeout=15)
        for ln in r.stdout.decode(errors="replace").splitlines():
            try: rec = json.loads(ln)
            except Exception: continue
            ts = rec.get("timestamp") or rec.get("t")
            if not ts: continue
            # Compare ISO timestamps lexically — Vector emits Z-suffixed RFC3339
            if ts >= since_ts: yield rec
    except Exception:
        return


def capture():
    """Sample one observation from Vector's JSONL streams + per-trajectory state."""
    now = time.time()
    iso = datetime.fromtimestamp(now).isoformat(timespec="seconds")
    obs = {"ts": now, "iso": iso}

    # Sample window: last 90 seconds of Vector data
    import datetime as _dt
    since = (datetime.utcnow() - _dt.timedelta(seconds=90)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- HOST METRICS via Vector ---
    # Vector ships one row per (metric_name, scrape). Pick the latest of each.
    latest_metrics = {}
    for rec in _tail_jsonl(VECTOR_HOST_METRICS, since):
        name = rec.get("name")
        if not name: continue
        v = rec.get("gauge") or rec.get("counter") or {}
        val = v.get("value") if isinstance(v, dict) else None
        if val is None: continue
        latest_metrics[name] = (val, rec.get("timestamp", ""))
    # Project the bits we care about
    def get(k): return latest_metrics.get(k, (None, None))[0]
    obs["loadavg"] = f"{get('load1') or 0:.2f} {get('load5') or 0:.2f} {get('load15') or 0:.2f}"
    mem_total = get("memory_total_bytes") or 0
    mem_avail = get("memory_available_bytes") or 0
    mem_used = mem_total - mem_avail if mem_total else 0
    obs["mem_kb"] = f"total={int(mem_total/1024)} used={int(mem_used/1024)} avail={int(mem_avail/1024)}"
    # CPU — Vector ships cpu_seconds_total per (cpu, mode) counters; we approximate idle ratio
    # via the most recent "idle" mode aggregate vs total
    cpu_idle = get("cpu_seconds_total_idle") or 0  # may not exist; approximate
    obs["mpstat_1s"] = f"vector_metrics_only loadavg1m={get('load1') or 0:.2f}"

    # --- DOCKER CONTAINER STATE via Vector ---
    # Last-seen records per container name in window
    containers_seen = {}
    for rec in _tail_jsonl(VECTOR_DOCKER, since, max_lines=5000):
        cn = rec.get("container_name")
        if cn: containers_seen[cn] = rec.get("timestamp", "")
    iter_n = sum(1 for n in containers_seen if n.startswith("iter_"))
    seqj_n = sum(1 for n in containers_seen if n.startswith("seqj_"))
    yb_n = sum(1 for n in containers_seen if n.startswith("yb_"))
    obs["containers_iter"] = iter_n
    obs["containers_seqj"] = seqj_n
    obs["containers_yb"] = yb_n
    obs["containers_total_recent"] = len(containers_seen)

    # --- PROCESS / PID state (still cheap subprocess; not in Vector) ---
    obs["round_robin_pid"] = sh("pgrep -f 'round_robin.py' | head -1")
    if obs["round_robin_pid"]:
        obs["round_robin_etime"] = sh(f"ps -p {obs['round_robin_pid']} -o etime= | tr -d ' '")
    obs["yb_build_pid"] = sh("pgrep -f 'build_yearback_dataset.py' | head -1")
    if obs["yb_build_pid"]:
        obs["yb_build_etime"] = sh(f"ps -p {obs['yb_build_pid']} -o etime= | tr -d ' '")

    # --- TRAJECTORY / DATASET PROGRESS (file-based, fast) ---
    obs["traj_count"] = sh_int(f"ls {ITER_TRAJ_DIR} 2>/dev/null | wc -l")
    if os.path.isdir(ITER_TRAJ_DIR):
        passes = fails = excs = 0
        for slug in os.listdir(ITER_TRAJ_DIR):
            tp = f"{ITER_TRAJ_DIR}/{slug}/trajectory.json"
            if not os.path.exists(tp): continue
            try:
                t = json.load(open(tp))
                fv = t.get("final_verdict", "?")
                if fv == "PASS": passes += 1
                elif fv.startswith("EXC") or fv == "?": excs += 1
                else: fails += 1
            except Exception:
                excs += 1
        obs["iter_pass"] = passes
        obs["iter_fail"] = fails
        obs["iter_exc"] = excs

    yb_probes_dir = f"{BASE}/attempt_8/yearback_probes"
    if os.path.isdir(yb_probes_dir):
        yb_sel = yb_skip = 0
        for f in os.listdir(yb_probes_dir):
            try:
                r = json.load(open(f"{yb_probes_dir}/{f}"))
                if r.get("selected"): yb_sel += 1
                elif r.get("skipped_reason"): yb_skip += 1
            except Exception: continue
        obs["yb_selected"] = yb_sel
        obs["yb_skipped"] = yb_skip
        obs["yb_total_processed"] = yb_sel + yb_skip

    # --- APP-LOG SAMPLE via Vector ---
    # Pull last 50 lines from the most recent log file in window, surface error-flavored ones
    log_lines = []
    error_lines = []
    for rec in _tail_jsonl(VECTOR_APP_LOGS, since, max_lines=5000):
        msg = rec.get("message", "")
        fil = rec.get("file", "")
        log_lines.append((rec.get("timestamp", ""), fil, msg))
        if any(s in msg for s in ("[ERROR]", "Caused by:", "java.lang.", "FAIL", "BUILD FAILURE")):
            error_lines.append((rec.get("timestamp", ""), fil, msg))
    obs["log_recent_FAIL_count"] = sum(1 for _, _, m in log_lines if "verdict: FAIL" in m)
    obs["log_recent_PASS_count"] = sum(1 for _, _, m in log_lines if "verdict: PASS" in m)
    # Keep a compact tail (last 25 lines of FAIL/PASS for the digest prompt)
    important = [l for l in log_lines if "verdict:" in l[2] or any(s in l[2] for s in ("[ERROR]", "FAIL"))][-25:]
    obs["round_robin_log_tail"] = "\n".join(f"{f.split('/')[-1] if f else '?'}: {m}" for _, f, m in important)
    obs["error_lines_sample"] = [f"{f.split('/')[-1] if f else '?'}: {m[:200]}" for _, f, m in error_lines[-10:]]

    day = iso[:10]
    out_path = f"{TELEMETRY_DIR}/raw-{day}.jsonl"
    with open(out_path, "a") as f:
        f.write(json.dumps(obs) + "\n")
    return obs


SYSTEM_COMPACTOR = """You are the observation compactor for a long-running fitness loop that searches for OpenRewrite recipe sequences to migrate Java projects to Java 21. The loop runs as a multi-pass round-robin: each pass gives every still-FAILing repo K more attempts via a Qwen proposer, then moves to the next repo.

Your job: given the raw telemetry snapshot below, emit STRICT JSON with this exact shape (no prose before or after, no markdown fences):

{
  "rate_limiter": "<one sentence: which pipeline stage caps throughput right now>",
  "binding_constraint": "<one sentence: which resource (CPU / GPU / memory / disk / network / artifact resolution) is the cap, with numbers>",
  "anomalies": [
    "<one bullet per anomaly: stuck containers, repeated identical failures, oscillations, drifting progress, runaway resource use, EXC counts>"
  ],
  "material_change_vs_prior": "<one sentence: is anything materially different from the prior digest below? if not, say so explicitly>",
  "suggestion": "<one concrete unblock suggestion, specific, cite numbers>"
}

Be terse. Cite numbers from the snapshot. Skip happy-path observations; surface only what constrains throughput or signals trouble. Return ONLY the JSON object."""


def gather_window(window_min=60):
    """Collect recent raw samples + recent log tail into a single snapshot string."""
    cutoff = time.time() - window_min * 60
    samples = []
    for f in sorted(os.listdir(TELEMETRY_DIR)):
        if not f.startswith("raw-"): continue
        for ln in open(f"{TELEMETRY_DIR}/{f}"):
            try:
                r = json.loads(ln)
                if r.get("ts", 0) >= cutoff: samples.append(r)
            except Exception:
                continue
    return samples


def fingerprint(text):
    """Stable hash of the digest body for frog's-eyes change detection."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def latest_digest():
    today = datetime.now().isoformat()[:10]
    for f in sorted(os.listdir(TELEMETRY_DIR), reverse=True):
        if not f.startswith("digest-"): continue
        path = f"{TELEMETRY_DIR}/{f}"
        last = None
        for ln in open(path):
            try: last = json.loads(ln)
            except Exception: continue
        if last: return last
    return None


def call_qwen(system, user, max_tokens=4096, thinking=True):
    payload = {
        "model": PROPOSER_MODEL,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    req = urllib.request.Request(
        PROPOSER_URL + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {PROPOSER_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            d = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    out = d["choices"][0]["message"]["content"]
    if "</think>" in out: out = out.split("</think>", 1)[1]
    return out.strip(), None


def digest(window_min=60, force=False):
    samples = gather_window(window_min)
    if not samples:
        return {"ok": False, "reason": "no recent telemetry"}

    # Build the snapshot the compactor sees
    first = samples[0]; last = samples[-1]
    span_min = (last["ts"] - first["ts"]) / 60 if len(samples) > 1 else 0

    # Compute trend deltas
    delta = {}
    if len(samples) >= 2:
        for k in ("iter_pass", "iter_fail", "traj_count",
                  "containers_iter", "containers_seqj", "containers_yb",
                  "yb_selected", "yb_skipped", "yb_total_processed"):
            if k in first and k in last:
                delta[k] = last[k] - first[k]

    prev_digest = latest_digest()
    if prev_digest and isinstance(prev_digest.get("digest"), dict):
        prev_summary = json.dumps(prev_digest["digest"], indent=2)
    elif prev_digest:
        prev_summary = str(prev_digest.get("digest", ""))
    else:
        prev_summary = "(no prior digest)"

    snapshot = (
        f"Window: {first['iso']} to {last['iso']} ({span_min:.0f} min, {len(samples)} samples)\n"
        f"Latest sample: {json.dumps(last, indent=2)[:3000]}\n\n"
        f"Trend deltas over window: {json.dumps(delta)}\n\n"
        f"Recent log tail (round_robin): {last.get('round_robin_log_tail','')[:2000]}\n\n"
        f"--- previous digest emitted at {prev_digest['iso'] if prev_digest else 'N/A'} ---\n"
        f"{prev_summary[:1500]}\n"
    )

    used_mode = "thinking"
    text, err = call_qwen(SYSTEM_COMPACTOR, snapshot, max_tokens=2048, thinking=True)
    if err:
        return {"ok": False, "reason": f"qwen err: {err}"}

    def _try_extract(t):
        if not t: return None
        i = t.find("{")
        if i < 0: return None
        depth = 0; in_str = False; esc = False
        for j in range(i, len(t)):
            c = t[j]
            if esc: esc = False; continue
            if c == "\\" and in_str: esc = True; continue
            if c == '"': in_str = not in_str
            elif not in_str:
                if c == "{": depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        try: return json.loads(t[i:j+1])
                        except Exception: return None
        return None

    parsed = _try_extract(text)
    if parsed is None:
        # fallback: no-thinking mode (per AGENTS.md ff #5)
        text2, err2 = call_qwen(SYSTEM_COMPACTOR, snapshot, max_tokens=1024, thinking=False)
        if not err2:
            parsed = _try_extract(text2)
            if parsed is not None:
                used_mode = "no-think_fallback"
                text = text2

    # (parsed already populated above via _try_extract)

    # Fingerprint on the structured fields (not the raw text) so cosmetic Qwen drift doesn't falsely "change" state
    if parsed:
        canon = json.dumps({k: parsed.get(k) for k in
                            ("rate_limiter", "binding_constraint", "anomalies", "suggestion")},
                           sort_keys=True)
    else:
        canon = text or "(unparseable)"
    fp = fingerprint(canon)
    materially_changed = not prev_digest or prev_digest.get("fingerprint") != fp

    entry = {
        "ts": time.time(),
        "iso": datetime.now().isoformat(timespec="seconds"),
        "window_min": int(span_min) or window_min,
        "samples": len(samples),
        "fingerprint": fp,
        "qwen_mode": used_mode,
        "digest": parsed if parsed else {"raw": text, "parse_error": True},
        "emitted": materially_changed or force,
        "trend": delta,
        "snapshot_tail": {k: last.get(k) for k in
                          ("iter_pass", "iter_fail", "iter_exc", "traj_count",
                           "containers_iter", "containers_yb",
                           "yb_selected", "yb_skipped", "yb_total_processed",
                           "loadavg", "mpstat_1s")},
    }

    if entry["emitted"]:
        day = entry["iso"][:10]
        with open(f"{TELEMETRY_DIR}/digest-{day}.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")

    return entry


def loop(capture_s, digest_s):
    last_digest_at = 0
    while True:
        try:
            capture()
            now = time.time()
            if now - last_digest_at >= digest_s:
                e = digest()
                last_digest_at = now
                print(f"[{datetime.now().isoformat(timespec='seconds')}] digest: emitted={e.get('emitted')} fp={e.get('fingerprint','-')}", flush=True)
        except Exception as e:
            print(f"loop error: {type(e).__name__}: {e}", flush=True)
        time.sleep(capture_s)


def show():
    d = latest_digest()
    if not d:
        print("(no digest yet)")
        return
    print(f"=== latest digest @ {d['iso']}  (window {d['window_min']} min, {d['samples']} samples) ===")
    print(f"fingerprint: {d['fingerprint']}  emitted: {d['emitted']}")
    print(f"trend: {d.get('trend', {})}")
    print(f"snapshot tail: {d.get('snapshot_tail', {})}")
    print()
    body = d.get("digest")
    if isinstance(body, dict):
        if body.get("parse_error"):
            print("(unparseable JSON from Qwen, raw):")
            print(body.get("raw", ""))
        else:
            print(f"rate_limiter:        {body.get('rate_limiter')}")
            print(f"binding_constraint:  {body.get('binding_constraint')}")
            print(f"material_change:     {body.get('material_change_vs_prior')}")
            print(f"suggestion:          {body.get('suggestion')}")
            print(f"anomalies:")
            for a in body.get("anomalies", []) or []:
                print(f"  - {a}")
    else:
        print(body)


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("capture")
    p_d = sp.add_parser("digest")
    p_d.add_argument("--window-min", type=int, default=60)
    p_d.add_argument("--force", action="store_true")
    p_l = sp.add_parser("loop")
    p_l.add_argument("--capture-s", type=int, default=60)
    p_l.add_argument("--digest-s", type=int, default=600)
    sp.add_parser("show")
    args = ap.parse_args()
    if args.cmd == "capture":
        r = capture()
        print(json.dumps({k: v for k, v in r.items() if k != "round_robin_log_tail"}, indent=2))
    elif args.cmd == "digest":
        r = digest(args.window_min, args.force)
        print(json.dumps({k: r.get(k) for k in ("ok", "iso", "samples", "fingerprint", "emitted", "trend")}, indent=2))
        if r.get("digest"): print("\n---\n" + r["digest"])
    elif args.cmd == "loop":
        loop(args.capture_s, args.digest_s)
    elif args.cmd == "show":
        show()


if __name__ == "__main__":
    main()

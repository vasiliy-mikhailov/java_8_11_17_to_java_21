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
ITER_TRAJ_DIR = f"{BASE}/attempt_7/per_repo_iter"


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
VLLM_URL = ENV.get("VLLM_BASE_URL", "https://inference.mikhailov.tech/v1").rstrip("/")
VLLM_KEY = ENV.get("VLLM_API_KEY", "")
VLLM_MODEL = ENV.get("VLLM_MODEL", "qwen3.6-27b-fp8")


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


def capture():
    """Sample one observation and append to today's raw jsonl."""
    now = time.time()
    iso = datetime.fromtimestamp(now).isoformat(timespec="seconds")
    obs = {"ts": now, "iso": iso}

    obs["loadavg"] = sh("cat /proc/loadavg | awk '{print $1,$2,$3}'")
    obs["uptime"] = sh("uptime -p")
    obs["mpstat_1s"] = sh("mpstat 1 1 2>/dev/null | tail -1 | awk '{print \"usr=\"$3\" sys=\"$5\" iowait=\"$6\" idle=\"$12}'")
    obs["mem_kb"] = sh("free -k | awk '/Mem:/ {print \"total=\"$2\" used=\"$3\" avail=\"$7}'")
    obs["disk_root"] = sh("df -h / | awk 'NR==2 {print \"used=\"$3\" avail=\"$4\" pct=\"$5}'")
    obs["containers_iter"] = sh_int("docker ps --format '{{.Names}}' 2>/dev/null | grep -c '^iter_'")
    obs["containers_seqj"] = sh_int("docker ps --format '{{.Names}}' 2>/dev/null | grep -c '^seqj_'")
    obs["containers_total"] = sh_int("docker ps -q 2>/dev/null | wc -l")
    obs["round_robin_pid"] = sh("pgrep -f 'round_robin.py' | head -1")
    if obs["round_robin_pid"]:
        obs["round_robin_etime"] = sh(f"ps -p {obs['round_robin_pid']} -o etime= | tr -d ' '")
    obs["traj_count"] = sh_int(f"ls {ITER_TRAJ_DIR} 2>/dev/null | wc -l")

    # Per-verdict counts in iterator
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

    # Recent round_robin log tail (last 30 lines)
    if os.path.exists(ROUND_ROBIN_LOG):
        obs["round_robin_log_tail"] = sh(f"tail -30 {ROUND_ROBIN_LOG}")
        obs["round_robin_log_mtime"] = os.path.getmtime(ROUND_ROBIN_LOG)

    # Recent error / warn counts in the log
    if os.path.exists(ROUND_ROBIN_LOG):
        obs["log_recent_FAIL_count"] = sh_int(f"tail -500 {ROUND_ROBIN_LOG} 2>/dev/null | grep -c 'verdict: FAIL'")
        obs["log_recent_PASS_count"] = sh_int(f"tail -500 {ROUND_ROBIN_LOG} 2>/dev/null | grep -c 'verdict: PASS'")

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
        "model": VLLM_MODEL,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    req = urllib.request.Request(
        VLLM_URL + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {VLLM_KEY}"},
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
                  "containers_iter", "containers_seqj"):
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
                           "containers_iter", "loadavg", "mpstat_1s")},
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

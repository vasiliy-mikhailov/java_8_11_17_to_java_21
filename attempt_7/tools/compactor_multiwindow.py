"""ff #7 compactor — multi-window digest (10s / 1min / 10min / 60min).

Reads Vector's JSONL streams (host_metrics, docker, app_logs) PLUS the OpenHands
event stream (/var/log/observe/openhands.jsonl) directly, aggregates each over
four time windows, hands the multi-resolution snapshot to Qwen AWQ, and emits
one digest that surfaces anomalies by window-to-window comparison.

Anomaly heuristics fed to the model:
  spike      : signal present in 10s window but absent (or much smaller per-min)
               in 10min/60min baseline → a fresh event the operator might miss.
  recovered  : signal present in 60min baseline but absent in the last 60s →
               whatever was going wrong has stopped; pin it before forgetting.
  oscillating: signal alternates across windows non-monotonically.

Usage:
  compactor_multiwindow.py digest        # one-shot multi-window digest
  compactor_multiwindow.py snapshot      # print the raw multi-window snapshot
                                         # the model would see (no LLM call)
"""
import os, sys, json, time, subprocess, urllib.request, hashlib, argparse
from datetime import datetime, timezone

BASE = "/home/vmihaylov/java_8_11_17_to_java_21"
TELEMETRY_DIR = f"{BASE}/attempt_7/telemetry"
os.makedirs(TELEMETRY_DIR, exist_ok=True)

# Reuse compactor.py's env loader / call_qwen / fingerprint
sys.path.insert(0, f"{BASE}/attempt_7/tools")
from compactor import load_env, fingerprint, call_qwen, latest_digest  # type: ignore

ENV = load_env()
VECTOR_HOST_METRICS = "/var/log/observe/host_metrics.jsonl"
VECTOR_DOCKER       = "/var/log/observe/docker.jsonl"
VECTOR_APP_LOGS     = "/var/log/observe/app_logs.jsonl"
OH_EVENTS           = "/var/log/observe/openhands.jsonl"

WINDOWS = [10, 60, 600, 3600]  # seconds


def _iso_z(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _tail_since(path, since_ts, max_lines=200000):
    """Yield JSONL rows whose `timestamp` is >= since_ts (ISO string compare)."""
    if not os.path.exists(path): return
    try:
        r = subprocess.run(["tail", "-n", str(max_lines), path],
                           capture_output=True, timeout=15)
        cutoff = _iso_z(since_ts)
        for ln in r.stdout.decode(errors="replace").splitlines():
            try: rec = json.loads(ln)
            except Exception: continue
            ts = rec.get("timestamp")
            if not ts: continue
            if ts >= cutoff: yield rec
    except Exception:
        return


def gather_openhands(seconds):
    """Counts/aggregates over OpenHands events in the last `seconds`."""
    since = time.time() - seconds
    by_event = {}; by_tool = {}; convs = set(); errors = 0; thoughts = 0
    total = 0
    for r in _tail_since(OH_EVENTS, since):
        total += 1
        et = r.get("event_type") or "?"
        by_event[et] = by_event.get(et, 0) + 1
        tn = r.get("tool_name")
        if tn:
            by_tool[tn] = by_tool.get(tn, 0) + 1
        if et == "ConversationErrorEvent": errors += 1
        if tn == "think": thoughts += 1
        cid = r.get("conv_id")
        if cid: convs.add(cid)
    return {
        "total_events": total,
        "by_event_type": by_event,
        "by_tool": by_tool,
        "convs_active": len(convs),
        "errors": errors,
        "thoughts": thoughts,
    }


def gather_docker(seconds):
    since = time.time() - seconds
    by_container = {}; errors = 0; total = 0
    for r in _tail_since(VECTOR_DOCKER, since):
        total += 1
        c = r.get("container_name") or "?"
        by_container[c] = by_container.get(c, 0) + 1
        msg = (r.get("message") or "").lower()
        if "error" in msg or "exception" in msg or "fatal" in msg: errors += 1
    # Top 8 chattiest containers
    top = sorted(by_container.items(), key=lambda x: -x[1])[:8]
    return {
        "total_lines": total,
        "errors": errors,
        "top_containers": dict(top),
    }


def gather_app_logs(seconds):
    since = time.time() - seconds
    total = 0; errors = 0
    by_file = {}
    for r in _tail_since(VECTOR_APP_LOGS, since):
        total += 1
        f = r.get("file") or "?"
        by_file[f] = by_file.get(f, 0) + 1
        msg = (r.get("message") or "").lower()
        if "error" in msg or "exception" in msg or "fatal" in msg or "[error]" in msg:
            errors += 1
    top = sorted(by_file.items(), key=lambda x: -x[1])[:5]
    return {
        "total_lines": total,
        "errors": errors,
        "top_files": dict(top),
    }


_METRIC_KINDS = {
    # gauges — report first/last/min/max so windows actually differ on slow-moving signals
    "load1": "gauge", "load5": "gauge", "load15": "gauge",
    "memory_active_bytes": "gauge",
    "memory_available_bytes": "gauge",
    "filesystem_free_bytes": "gauge",
    # counters — only delta over the window matters; absolute is a red herring
    "cpu_seconds_total": "counter",
    "disk_read_bytes_total": "counter",
    "disk_written_bytes_total": "counter",
    "network_receive_bytes_total": "counter",
    "network_transmit_bytes_total": "counter",
}


def gather_host_metrics(seconds):
    """Per-metric aggregates over the window.

    Vector emits one row per metric per scrape; previous version took only the
    latest value, which made adjacent windows look identical on slow gauges (the
    compactor correctly flagged this as a frozen-scraper false alarm). Now:
      - gauges:   {first, last, min, max} so a flat load1 reads as `last==min==max`,
                  a spike reads as `max > avg(first,last)`.
      - counters: {delta} over the window — the only thing that means anything,
                  since absolute counter values don't compare across windows.
    """
    since = time.time() - seconds
    by_metric = {}  # name -> list[(ts, value)]
    for r in _tail_since(VECTOR_HOST_METRICS, since, max_lines=20000):
        name = r.get("name") or ""
        if name not in _METRIC_KINDS:
            continue
        # Aggregate across all collector tags (cpu mode, etc.) by summing per timestamp
        v = (r.get("counter") or r.get("gauge") or {}).get("value")
        ts = r.get("timestamp")
        if v is None or ts is None:
            continue
        by_metric.setdefault(name, []).append((ts, float(v)))
    out = {}
    for name, samples in by_metric.items():
        samples.sort()
        vals = [v for _, v in samples]
        if not vals:
            continue
        kind = _METRIC_KINDS[name]
        if kind == "counter":
            out[name] = {"delta": round(vals[-1] - vals[0], 3), "n": len(vals)}
        else:
            out[name] = {
                "first": round(vals[0], 3),
                "last": round(vals[-1], 3),
                "min": round(min(vals), 3),
                "max": round(max(vals), 3),
                "n": len(vals),
            }
    return out


def gather_window(seconds):
    return {
        "openhands":     gather_openhands(seconds),
        "docker":        gather_docker(seconds),
        "app_logs":      gather_app_logs(seconds),
        "host_metrics":  gather_host_metrics(seconds),
    }


def build_multi_window():
    return {f"{s}s": gather_window(s) for s in WINDOWS}


SYSTEM_MULTIWINDOW = """You are the multi-window observation compactor for a long-running fitness loop that searches for OpenRewrite recipe sequences to migrate Java projects to Java 21.

Four observation windows are provided side-by-side: 10s, 60s, 600s (10 min), 3600s (1 hour). Each window contains counts/aggregates from four streams: OpenHands investigator events, Docker container logs, app-log files, and host metrics.

Your job: detect anomalies by comparing windows.
- spike       — signal in 10s/60s that is absent (or per-second much smaller) in 600s/3600s.
- recovered   — signal present in 3600s that has stopped in 60s.
- oscillating — counts alternate non-monotonically across windows.
- steady      — proportional across all four windows; mention only if it is the binding constraint.

Emit STRICT JSON (no prose, no fences):

{
  "rate_limiter": "<which pipeline stage caps throughput right now, one sentence>",
  "binding_constraint": "<which resource — CPU / GPU / memory / disk / network / artifact resolution / investigator depth — caps throughput, with numbers>",
  "anomalies": [
    {"kind": "spike|recovered|oscillating|steady", "stream": "openhands|docker|app_logs|host_metrics", "signal": "<what>", "windows": "<which windows show it>", "note": "<concrete numbers>"}
  ],
  "material_change_vs_prior": "<one sentence: is anything materially different from the prior digest? if not, say so explicitly>",
  "suggestion": "<one concrete unblock suggestion, specific, cite numbers>"
}

Cite numbers from the snapshot. Skip happy-path observations. Return ONLY the JSON object."""


def _try_extract_json(t):
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


def digest_multi(force=False):
    snap = build_multi_window()
    prev = latest_digest()
    prev_summary = json.dumps(prev.get("digest"), indent=2)[:1500] if prev else "(no prior digest)"

    user = (
        "Multi-window snapshot:\n"
        + json.dumps(snap, indent=2)
        + f"\n\n--- previous digest at {prev['iso'] if prev else 'N/A'} ---\n{prev_summary}\n"
    )
    # 6144 token budget so thinking mode has room to emit the final JSON after </think>.
    text, err = call_qwen(SYSTEM_MULTIWINDOW, user, max_tokens=6144, thinking=True)
    if err:
        return {"ok": False, "reason": f"qwen err: {err}"}
    parsed = _try_extract_json(text)
    if parsed is None:
        # Fallback: no-thinking, much smaller budget needed for just the JSON.
        text2, err2 = call_qwen(SYSTEM_MULTIWINDOW, user, max_tokens=2048, thinking=False)
        if not err2:
            parsed = _try_extract_json(text2)

    if parsed:
        canon = json.dumps({k: parsed.get(k) for k in
                            ("rate_limiter", "binding_constraint", "anomalies", "suggestion")},
                           sort_keys=True)
    else:
        canon = text or "(unparseable)"
    fp = fingerprint(canon)
    materially_changed = not prev or prev.get("fingerprint") != fp

    entry = {
        "ts": time.time(),
        "iso": datetime.now().isoformat(timespec="seconds"),
        "windows_s": WINDOWS,
        "kind": "multiwindow",
        "fingerprint": fp,
        "digest": parsed if parsed else {"raw": text, "parse_error": True},
        "emitted": materially_changed or force,
        "snapshot": snap,
    }
    if entry["emitted"]:
        day = entry["iso"][:10]
        with open(f"{TELEMETRY_DIR}/digest-{day}.jsonl", "a") as f:
            f.write(json.dumps(entry) + "\n")
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["digest", "snapshot"])
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.cmd == "snapshot":
        snap = build_multi_window()
        print(json.dumps(snap, indent=2))
        return
    if args.cmd == "digest":
        e = digest_multi(force=args.force)
        print(json.dumps(e, indent=2, default=str))


if __name__ == "__main__":
    main()

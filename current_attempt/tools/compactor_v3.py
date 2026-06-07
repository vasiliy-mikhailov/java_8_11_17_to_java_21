import json, os, time, urllib.request, re
from datetime import datetime, timezone

# observability compactor (frog's eye, P10). Three-layer cascade:
#   FAST   <- raw /var/log streams (via Vector sinks)
#   MEDIUM <- the FAST digest
#   SLOW   <- the MEDIUM digest
# Each layer emits its own rolling digest. Cadence is data-driven (no wall-clock
# intervals): MEDIUM folds every MED_EVERY fast folds, SLOW every SLOW_EVERY medium.
# Endpoint/model/key from .env -> Qwen3.6 MoE AWQ via the gateway.
_OBSENV = {}
for _l in open("/home/vmihaylov/java_8_11_17_to_java_21/.env"):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _v = _l.split("=", 1); _OBSENV[_k] = _v.strip().strip('"').strip("'")
OBS_URL = _OBSENV.get("OBSERVABILITY_COMPACTOR_BASE_URL", "https://inference.mikhailov.tech/qwen-3.6-27b-awq/v1").rstrip("/")
OBS_MODEL = _OBSENV.get("OBSERVABILITY_COMPACTOR_MODEL", "qwen3.6-27b-awq")
OBS_KEY = _OBSENV.get("OBSERVABILITY_COMPACTOR_API_KEY") or _OBSENV.get("PROPOSER_API_KEY", "")

# INPUT: Vector's sink files (Vector excludes /var/log/observe/*.jsonl, so no cycle).
OBS_DIR = "/var/log/observe"
STREAMS = {"host": f"{OBS_DIR}/host_metrics.jsonl",
           "docker": f"{OBS_DIR}/docker.jsonl",
           "app": f"{OBS_DIR}/app_logs.jsonl"}

# OUTPUT: the three layer digests live OUTSIDE /var/log so Vector never tails (and
# loops on) our own output.
OUT_DIR = "/home/vmihaylov/observe"
FAST_LOG = f"{OUT_DIR}/fast.jsonl"
MED_LOG  = f"{OUT_DIR}/medium.jsonl"
SLOW_LOG = f"{OUT_DIR}/slow.jsonl"

OFFSETS_FILE = "/home/vmihaylov/.compactor.offsets"  # read positions, survive restarts
STATE_FILE   = "/home/vmihaylov/.compactor.state"    # rolling layer states, so folds survive restarts

OUTPUT_BUDGET = 4000     # max_tokens cap: bounds generation so a fold completes within the timeout even when
                         # the MoE is slow (it drops to ~12 tok/s when GPU0's proposer saturates the box)
NEW_BUDGET = 8000        # ~8k tokens of new (collapsed) events fed per FAST fold
RECENT_KEEP = 8          # raw events kept after a fast fold (continuity for the next per-sample alarm)
TAIL_INTERVAL_S = 5      # poll cadence (loop sleep only — NOT a compaction interval)
MAX_INGEST = 5000        # cap lines ingested per stream per tick so a huge backlog can't OOM the buffer
COMPACT_SAMPLES = 4000   # FAST folds once this many raw events have accrued
MED_EVERY = 2            # one MEDIUM fold per this many FAST folds  (fast~5min -> medium~10min horizon)
SLOW_EVERY = 2           # one SLOW fold per this many MEDIUM folds (-> slow~20min horizon)

# ---- shared output schema + per-layer fold instructions -------------------------
_SCHEMA = (
    "Return JSON ONLY: {\"summary\":\"<one or two sentences on overall host state>\","
    "\"anomalies\":[{\"what\":\"<short label>\",\"kind\":\"<error|security|resource|build|network|churn|info>\","
    "\"n\":<int>,\"distinct\":<int>,\"span\":[\"<first>\",\"<last>\"],"
    "\"last\":\"<verbatim full text of most recent occurrence>\","
    "\"params\":[{\"what\":\"<the value>\",\"n\":<int>,\"when\":[\"<first>\",\"<last>\"]}]}]} "
    "Keep at most ~12 anomalies (most severe/active first); fold the rest into summary. Be concise. JSON only, no prose.")

FAST_SYSTEM = (
    "You maintain the FAST rolling digest of host state — the most recent, fine-grained view. You get the "
    "PRIOR fast digest (JSON) and a batch of NEW collapsed log events (repeats already counted: each carries "
    "n, distinct, span [first,last], last full text, and params — the per-value breakdown [{what,n,when}]). "
    "Fold NEW into PRIOR: a continuing anomaly -> add its n, extend span, refresh last+params; a new anomaly "
    "-> add it; a stale anomaly with no activity in this batch -> DROP it. " + _SCHEMA)

MEDIUM_SYSTEM = (
    "You maintain the MEDIUM digest — a longer-horizon view built FROM the FAST layer. The NEW input is the "
    "current FAST digest's anomalies: these are cumulative SNAPSHOTS, not new disjoint events. Merge by "
    "anomaly identity: for one that continues take its LATEST n and the UNION of spans — do NOT sum across "
    "snapshots. Add newly-appearing anomalies. Drop anomalies absent across many updates. " + _SCHEMA)

SLOW_SYSTEM = (
    "You maintain the SLOW digest — the longest-horizon, big-picture view built FROM the MEDIUM layer. The "
    "NEW input is the current MEDIUM digest's anomalies (cumulative snapshots, not new events). Keep the "
    "durable, recurring picture: merge by identity (latest n, union spans, never sum), and drop only "
    "anomalies long absent. " + _SCHEMA)


def approx_tokens(t): return (len(t) + 1) // 2  # conservative upper bound


def _extract_json(content):
    """Pull the first valid JSON object out of a model reply. Uses a real JSON parser
    (raw_decode) so braces inside quoted strings — e.g. Vector's 'source{component_kind=...}'
    log lines in verbatim 'last' fields — don't break extraction at any nesting depth.
    Tolerates ```json fences / prose."""
    s = (content or "").strip()
    if s.startswith("```"):
        body = s[3:]
        if body[:4].lower().startswith("json"):
            body = body[4:]
        end = body.rfind("```")
        s = (body[:end] if end != -1 else body).strip()
    dec = json.JSONDecoder()
    start = s.find("{")
    while start != -1:
        try:
            obj, _ = dec.raw_decode(s, start)
            return obj
        except json.JSONDecodeError:
            start = s.find("{", start + 1)
    return None


def ask_qwen(system, user, max_tokens=OUTPUT_BUDGET):
    body = {"model": OBS_MODEL, "messages": [
            {"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0.0, "max_tokens": max_tokens, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(OBS_URL + "/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": "Bearer " + OBS_KEY, "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=480) as r:
                content = (json.loads(r.read())["choices"][0]["message"].get("content") or "").strip()
            obj = _extract_json(content)
            return obj if obj is not None else {"raw": content[:300]}
        except Exception as e:
            if attempt == 2: return {"err": str(e)}
            time.sleep(2 ** attempt)


# ---- rolling state ---------------------------------------------------------------
buffer = []
offsets = {}
fast_state = None      # {summary, anomalies}
medium_state = None
slow_state = None
fast_count = 0         # fast folds since the last medium fold
medium_count = 0       # medium folds since the last slow fold
last_alarm = ""


def init_offsets_at_end():
    """Skip Vector's backlog: start reading from current end of each file."""
    for stream, path in STREAMS.items():
        try:
            offsets[stream] = os.path.getsize(path)
        except Exception:
            offsets[stream] = 0
    print(f"init offsets: {offsets}", flush=True)


def save_state():
    """Persist read offsets + all three rolling digests (and the cascade counters) so a
    restart resumes where it left off and the folds keep rolling."""
    try:
        tmp = OFFSETS_FILE + ".tmp"
        with open(tmp, "w") as f: json.dump(offsets, f)
        os.replace(tmp, OFFSETS_FILE)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"fast": fast_state, "medium": medium_state, "slow": slow_state,
                       "fast_count": fast_count, "medium_count": medium_count}, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass


def load_state():
    """Resume from persisted offsets + layer states; cold-start at end-of-file otherwise."""
    global fast_state, medium_state, slow_state, fast_count, medium_count
    try:
        with open(OFFSETS_FILE) as f:
            saved = json.load(f)
        for stream in STREAMS:
            offsets[stream] = int(saved.get(stream, 0))
        print(f"resumed offsets: {offsets}", flush=True)
    except Exception:
        init_offsets_at_end()
    try:
        with open(STATE_FILE) as f:
            st = json.load(f)
        fast_state = st.get("fast"); medium_state = st.get("medium"); slow_state = st.get("slow")
        fast_count = st.get("fast_count", 0); medium_count = st.get("medium_count", 0)
        nz = lambda s: len(s.get("anomalies", [])) if s else 0
        print(f"resumed states: fast={nz(fast_state)} medium={nz(medium_state)} slow={nz(slow_state)}", flush=True)
    except Exception:
        pass


def tail_new_lines():
    for stream, path in STREAMS.items():
        if not os.path.exists(path): continue
        try:
            new = []
            with open(path) as f:
                f.seek(offsets[stream])
                for _ in range(MAX_INGEST):   # bounded: don't slurp a huge backlog into memory at once
                    line = f.readline()
                    if not line: break
                    new.append(line)
                offsets[stream] = f.tell()
            for line in new:
                line = line.strip()
                if not line: continue
                try: ev = json.loads(line)
                except: continue
                t = ev.get("timestamp") or ev.get("@timestamp") or datetime.now(timezone.utc).isoformat()
                if stream == "host":
                    compact_ev = {"name": ev.get("name", "?"),
                                  "val": (ev.get("gauge", {}) or ev.get("counter", {}) or {}).get("value"),
                                  "tags": ev.get("tags", {})}
                elif stream == "docker":
                    compact_ev = {"container": ev.get("container_name"),
                                  "msg": (ev.get("message") or "")[:1200]}
                else:
                    compact_ev = {"file": (ev.get("file", "") or "").split("/")[-1],
                                  "msg": (ev.get("message") or "")[:1200]}
                buffer.append({"t": t, "s": stream, "e": compact_ev})
        except Exception: pass


def per_sample_alarm():
    """Instant surfacing of fresh error bursts, written to the FAST log between folds."""
    global last_alarm
    if len(buffer) < 5: return
    recent = buffer[-50:]
    errs = [b for b in recent if b["s"] == "app" and re.search(r"\b(error|exception|traceback)\b", b["e"].get("msg", ""), re.I)]
    if not errs: return
    sigs = sorted({(b["e"].get("file"), b["e"].get("msg", "")[:60]) for b in errs})
    sig_str = " | ".join(f"{f}: {m[:50]}" for f, m in sigs[:3])
    alarm = f"{len(errs)} error events from {len(sigs)} sources — {sig_str}"
    if alarm == last_alarm: return
    last_alarm = alarm
    entry = {"t": datetime.now(timezone.utc).isoformat(), "layer": "fast", "kind": "alarm", "facts": alarm}
    with open(FAST_LOG, "a") as f: f.write(json.dumps(entry) + "\n")
    print(f"ALARM: {alarm[:200]}", flush=True)


_NORM = re.compile(r"[0-9a-f]{6,}|\d+|0x[0-9a-f]+")


def _sig(b):
    """Signature for collapsing repetitions: stream + source + message with the
    variable bits (numbers, hex ids, veth names, pids, timestamps) masked out."""
    e = b.get("e", {}) or {}
    msg = e.get("msg") or e.get("name") or ""
    key = str(e.get("file") or e.get("container") or "").rsplit("/", 1)[-1]
    return (b.get("s"), key, _NORM.sub("#", str(msg))[:100])


def collapse(buf):
    """Collapse repeats into one group carrying the count, the per-value breakdown, and
    the time span — the ~100-500x reduction that lets 8k of 'new' span a useful window."""
    groups = {}
    for b in buf:
        s = _sig(b)
        e = b.get("e", {}) or {}
        msg = e.get("msg") or e.get("name") or json.dumps(e)
        t = (b.get("t") or "")[:19]
        v = msg[:200]  # the distinct value within the group (e.g. the specific IP / path / iface)
        g = groups.get(s)
        if g is None:
            groups[s] = {"n": 1, "s": b.get("s"), "span": [t, t], "last": msg,
                         "vars": {v: [1, t, t]}}  # value -> [count, first_seen, last_seen]
        else:
            g["n"] += 1
            if t and t < g["span"][0]: g["span"][0] = t
            if t and t >= g["span"][1]: g["span"][1] = t
            g["last"] = msg  # buffer is time-ordered, so the final occurrence is the most recent
            pv = g["vars"].get(v)
            if pv is not None:
                pv[0] += 1
                if t and t < pv[1]: pv[1] = t
                if t and t >= pv[2]: pv[2] = t
            elif len(g["vars"]) < 256:
                g["vars"][v] = [1, t, t]
    out = []
    for g in groups.values():
        top = sorted(g["vars"].items(), key=lambda kv: -kv[1][0])[:3]
        params = [{"what": val, "n": cnt, "when": [first, last]} for val, (cnt, first, last) in top]
        out.append({"n": g["n"], "s": g["s"], "span": g["span"],
                    "distinct": len(g["vars"]), "last": g["last"], "params": params})
    return out


def fold(prior_digest, new_items, system):
    """Rolling fold: prior digest (JSON) + new items -> updated digest (JSON). For FAST the
    new items are collapsed log groups; for MEDIUM/SLOW they are the lower layer's anomalies."""
    prior_json = json.dumps(prior_digest or {"summary": "(none yet)", "anomalies": []})
    user = ("PRIOR DIGEST (JSON):\n" + prior_json +
            "\n\nNEW INPUT:\n" + "\n".join(json.dumps(x) for x in new_items))
    resp = ask_qwen(system, user)
    return {"summary": resp.get("summary", "") or "",
            "anomalies": [a for a in (resp.get("anomalies", []) or []) if isinstance(a, dict)]}


def write_digest(path, layer, state, extra=None):
    entry = {"t": datetime.now(timezone.utc).isoformat(), "layer": layer,
             "summary": state["summary"], "anomalies": state["anomalies"]}
    if extra: entry.update(extra)
    with open(path, "a") as f: f.write(json.dumps(entry) + "\n")
    print(f"{layer.upper()} done. anomalies={len(state['anomalies'])}", flush=True)


def run_slow():
    global slow_state
    slow_state = fold(slow_state, (medium_state or {}).get("anomalies", []), SLOW_SYSTEM)
    write_digest(SLOW_LOG, "slow", slow_state)


def run_medium():
    global medium_state, medium_count
    medium_state = fold(medium_state, (fast_state or {}).get("anomalies", []), MEDIUM_SYSTEM)
    write_digest(MED_LOG, "medium", medium_state)
    medium_count += 1
    if medium_count >= SLOW_EVERY:
        medium_count = 0
        run_slow()


def run_fast():
    global buffer, fast_state, fast_count
    collapsed = collapse(buffer)            # dedup repetitions so 8k of "new" spans a useful window
    collapsed.sort(key=lambda g: -g["n"])   # busiest groups first
    new_groups, tok = [], 0
    for g in collapsed:
        gt = approx_tokens(json.dumps(g))
        if new_groups and tok + gt > NEW_BUDGET: break
        new_groups.append(g); tok += gt
    print(f"FAST samples={len(buffer)} -> {len(collapsed)} distinct, feeding {len(new_groups)} groups (~{tok} tok)", flush=True)
    fast_state = fold(fast_state, new_groups, FAST_SYSTEM)
    write_digest(FAST_LOG, "fast", fast_state, {"samples": len(buffer), "distinct_groups": len(collapsed)})
    buffer = buffer[-RECENT_KEEP:]
    fast_count += 1
    if fast_count >= MED_EVERY:
        fast_count = 0
        run_medium()
    save_state()


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"compactor_v3: 3-layer cascade (fast<-logs, medium<-fast, slow<-medium); "
          f"COMPACT_SAMPLES={COMPACT_SAMPLES} MED_EVERY={MED_EVERY} SLOW_EVERY={SLOW_EVERY}", flush=True)
    load_state()
    while True:
        tail_new_lines()
        if buffer:
            per_sample_alarm()
            if len(buffer) >= COMPACT_SAMPLES:
                run_fast()
        time.sleep(TAIL_INTERVAL_S)


if __name__ == "__main__":
    main()

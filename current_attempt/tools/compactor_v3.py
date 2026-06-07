import json, os, time, urllib.request, re
from datetime import datetime, timezone

# observability compactor (frog's eye, P10) endpoint/model/key from .env -> Qwen3.6-27B-AWQ via gateway /awq route
_OBSENV = {}
for _l in open("/home/vmihaylov/java_8_11_17_to_java_21/.env"):
    _l = _l.strip()
    if _l and not _l.startswith("#") and "=" in _l:
        _k, _v = _l.split("=", 1); _OBSENV[_k] = _v.strip().strip('"').strip("'")
OBS_URL = _OBSENV.get("OBSERVABILITY_COMPACTOR_BASE_URL", "https://inference.mikhailov.tech/qwen-3.6-27b-awq/v1").rstrip("/")
OBS_MODEL = _OBSENV.get("OBSERVABILITY_COMPACTOR_MODEL", "qwen3.6-27b-awq")
OBS_KEY = _OBSENV.get("OBSERVABILITY_COMPACTOR_API_KEY") or _OBSENV.get("PROPOSER_API_KEY", "")

OBS_DIR = "/var/log/observe"
DIGEST = f"{OBS_DIR}/digest.jsonl"
CTX_BUDGET = 64 * 1024   # MoE (Qwen3.6-35B-A3B-AWQ) max-model-len = 65536
OUTPUT_BUDGET = 8000
SAFETY = 2000  # system prompt + wrappers
COMPACT_AT = int(CTX_BUDGET * 0.40)   # trigger compaction at 40% of budget
HARD_CAP = CTX_BUDGET - OUTPUT_BUDGET - SAFETY  # never send more than this
RECENT_KEEP = 8
DEEP_REVIEW_S = 90
TAIL_INTERVAL_S = 5

STREAMS = {"host": f"{OBS_DIR}/host_metrics.jsonl",
           "docker": f"{OBS_DIR}/docker.jsonl",
           "app": f"{OBS_DIR}/app_logs.jsonl"}

COMPACT_SYSTEM = (
    "You receive a rolling trajectory of host events with a prior compacted summary. "
    "Repeated events are pre-collapsed: each item carries \"n\" (occurrences), \"distinct\" (how many "
    "distinct variants), \"variants\" (a sample of the differing values), and \"span\" ([first,last] time). "
    "ALWAYS surface all of these — the count, the distinct variants, and the time span — e.g. "
    "'SSH auth failures n=100 from 3 IPs (168.x, 118.x, ...) span 11:20-13:05', or "
    "'veth churn n=8400 across many interfaces, continuous'. A high n or many distinct variants is itself a signal. "
    "Return JSON: {\"compacted_summary\":\"<paragraph ~20% of input; for each notable pattern/anomaly give its "
    "n, its distinct variants, and its time span>\",\"sustained_anomalies\":[\"<fact with n, variants, span>\"]} "
    "JSON only, no prose.")


def approx_tokens(t): return (len(t) + 1) // 2  # conservative upper bound


def ask_qwen(system, user, max_tokens=OUTPUT_BUDGET):
    body = {"model":OBS_MODEL,"messages":[
            {"role":"system","content":system},{"role":"user","content":user}],
            "temperature":0.0,"max_tokens":max_tokens,"chat_template_kwargs":{"enable_thinking":False}}
    req = urllib.request.Request(OBS_URL+"/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization":"Bearer "+OBS_KEY,"Content-Type":"application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=240) as r:
                content = (json.loads(r.read())["choices"][0]["message"].get("content") or "").strip()
            m = re.search(r"\{(?:[^{}]|(?:\{[^{}]*\}))*\}", content, re.DOTALL)
            return json.loads(m.group(0)) if m else {"raw": content[:300]}
        except Exception as e:
            if attempt == 2: return {"err": str(e)}
            time.sleep(2 ** attempt)


buffer = []
offsets = {}
compacted_summary = None
last_deep = time.time()
last_alarm = ""


def init_offsets_at_end():
    """Skip Vector's backlog: start reading from current end of each file."""
    for stream, path in STREAMS.items():
        try:
            sz = os.path.getsize(path)
            offsets[stream] = sz
        except Exception:
            offsets[stream] = 0
    print(f"init offsets: {offsets}", flush=True)


OFFSETS_FILE = "/home/vmihaylov/.compactor.offsets"  # outside /var/log so Vector doesn't tail it


def save_offsets():
    """Persist offsets after each successful compaction so a restart resumes where it
    left off (never drops the backlog). Saved offsets reflect condensed data only."""
    try:
        tmp = OFFSETS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(offsets, f)
        os.replace(tmp, OFFSETS_FILE)
    except Exception:
        pass


def load_or_init_offsets():
    """Resume from persisted offsets (process the backlog); only fall back to
    end-of-file on a true cold start with no saved offsets."""
    try:
        with open(OFFSETS_FILE) as f:
            saved = json.load(f)
        for stream in STREAMS:
            offsets[stream] = int(saved.get(stream, 0))
        print(f"resumed offsets from {OFFSETS_FILE}: {offsets}", flush=True)
    except Exception:
        init_offsets_at_end()


def tail_new_lines():
    for stream, path in STREAMS.items():
        if not os.path.exists(path): continue
        try:
            with open(path) as f:
                f.seek(offsets[stream])
                new = f.readlines()
                offsets[stream] = f.tell()
            for line in new:
                line = line.strip()
                if not line: continue
                try: ev = json.loads(line)
                except: continue
                t = ev.get("timestamp") or ev.get("@timestamp") or datetime.now(timezone.utc).isoformat()
                if stream == "host":
                    compact_ev = {"name": ev.get("name","?"),
                                  "val": (ev.get("gauge",{}) or ev.get("counter",{}) or {}).get("value"),
                                  "tags": ev.get("tags",{})}
                elif stream == "docker":
                    compact_ev = {"container": ev.get("container_name"),
                                  "msg": (ev.get("message") or "")[:200]}
                else:
                    compact_ev = {"file": (ev.get("file","") or "").split("/")[-1],
                                  "msg": (ev.get("message") or "")[:200]}
                buffer.append({"t": t, "s": stream, "e": compact_ev})
        except Exception: pass


def per_sample_alarm():
    global last_alarm
    if len(buffer) < 5: return
    recent = buffer[-50:]
    errs = [b for b in recent if b["s"] == "app" and re.search(r"\b(error|exception|traceback)\b", b["e"].get("msg",""), re.I)]
    if not errs: return
    # Dedupe by (file, first_60_chars)
    sigs = sorted({(b["e"].get("file"), b["e"].get("msg","")[:60]) for b in errs})
    sig_str = " | ".join(f"{f}: {m[:50]}" for f,m in sigs[:3])
    alarm = f"{len(errs)} error events from {len(sigs)} sources — {sig_str}"
    if alarm == last_alarm: return
    last_alarm = alarm
    entry = {"t": datetime.now(timezone.utc).isoformat(), "kind": "alarm", "facts": alarm}
    with open(DIGEST, "a") as f: f.write(json.dumps(entry) + "\n")
    print(f"ALARM: {alarm[:200]}", flush=True)


def _serialize(buf): return "\n".join(json.dumps(b) for b in buf)


def chunk_buffer(buf, chunk_token_cap):
    """Split buffer into time-ordered chunks whose serialization fits chunk_token_cap each."""
    chunks, cur, cur_tok = [], [], 0
    for b in buf:
        t = approx_tokens(json.dumps(b))
        if cur and cur_tok + t > chunk_token_cap:
            chunks.append(cur); cur, cur_tok = [], 0
        cur.append(b); cur_tok += t
    if cur: chunks.append(cur)
    return chunks


def summarize_chunk(buf_chunk, prior_summary):
    user = "(Prior compaction:)\n" + (prior_summary or "(none)") + "\n\n(Recent trajectory:)\n" + _serialize(buf_chunk)
    resp = ask_qwen(COMPACT_SYSTEM, user)
    return resp.get("compacted_summary","") or "", resp.get("sustained_anomalies",[]) or []


_NORM = re.compile(r"[0-9a-f]{6,}|\d+|0x[0-9a-f]+")


def _sig(b):
    """Signature for collapsing repetitions: stream + source + message with the
    variable bits (numbers, hex ids, veth names, pids, timestamps) masked out."""
    e = b.get("e", {}) or {}
    msg = e.get("msg") or e.get("name") or ""
    key = str(e.get("file") or e.get("container") or "").rsplit("/", 1)[-1]
    return (b.get("s"), key, _NORM.sub("#", str(msg))[:100])


def collapse(buf):
    """Collapse repeats into one group that carries the count AND the variations behind
    the masked signature + the time span — so the model can say e.g. 'SSH auth failures
    n=100 from 3 IPs (a,b,c), span 11:20-13:05', not just 'n=100'. This is the ~100-500x
    reduction (repetition summarized, not re-sent) while keeping the distinct variants."""
    groups = {}
    for b in buf:
        s = _sig(b)
        e = b.get("e", {}) or {}
        msg = e.get("msg") or e.get("name") or json.dumps(e)
        t = (b.get("t") or "")[:19]
        g = groups.get(s)
        if g is None:
            groups[s] = {"n": 1, "s": b.get("s"), "span": [t, t], "variants": {msg}}
        else:
            g["n"] += 1
            if t and t < g["span"][0]: g["span"][0] = t
            if t and t > g["span"][1]: g["span"][1] = t
            if len(g["variants"]) < 64:
                g["variants"].add(msg)
    out = []
    for g in groups.values():
        v = list(g["variants"])
        out.append({"n": g["n"], "s": g["s"], "span": g["span"],
                    "distinct": len(v), "variants": v[:8]})
    return out


def compact():
    global buffer, compacted_summary, last_deep
    prior_tok = approx_tokens(compacted_summary or "")
    chunk_cap = max(HARD_CAP - prior_tok - 1000, 10000)  # reserve room for prior + wrappers
    collapsed = collapse(buffer)  # dedup repetitions -> only distinct/anomalous events reach the model
    chunks = chunk_buffer(collapsed, chunk_cap)
    total_tokens = sum(approx_tokens(_serialize(c)) for c in chunks)
    print(f"COMPACT samples={len(buffer)} -> {len(collapsed)} distinct -> {len(chunks)} chunk(s), {total_tokens} tok, prior={prior_tok} tok", flush=True)
    chunk_summaries, all_sustained = [], []
    for c in chunks:
        summ, sus = summarize_chunk(c, compacted_summary)
        chunk_summaries.append(summ); all_sustained.extend(sus)
    if len(chunks) == 1:
        new_summary, sustained_final = chunk_summaries[0], all_sustained
    else:
        merge_user = ("(Prior compaction:)\n" + (compacted_summary or "(none)") +
                      "\n\n(Chunk summaries to merge into one:)\n" + "\n---\n".join(chunk_summaries))
        merge_resp = ask_qwen(COMPACT_SYSTEM, merge_user)
        new_summary = merge_resp.get("compacted_summary","") or " | ".join(chunk_summaries)
        sustained_final = merge_resp.get("sustained_anomalies") or all_sustained
    compacted_summary = new_summary
    entry = {"t": datetime.now(timezone.utc).isoformat(), "kind":"compaction",
             "samples_compacted": len(buffer), "input_tokens": total_tokens, "chunks": len(chunks),
             "compacted_summary": compacted_summary, "sustained_anomalies": sustained_final}
    with open(DIGEST, "a") as f: f.write(json.dumps(entry)+"\n")
    print(f"COMPACT done. chunks={len(chunks)} sustained={sustained_final[:3]}", flush=True)
    buffer = buffer[-RECENT_KEEP:]
    last_deep = time.time()
    save_offsets()


def main():
    print(f"compactor_v3: resume backlog, DEEP_REVIEW={DEEP_REVIEW_S}s, HARD_CAP={HARD_CAP} tok", flush=True)
    load_or_init_offsets()
    while True:
        tail_new_lines()
        if buffer:
            per_sample_alarm()
            buf_text = "\n".join(json.dumps(b) for b in buffer)
            buf_tokens = approx_tokens((compacted_summary or "") + buf_text)
            if (buf_tokens >= COMPACT_AT or (time.time() - last_deep) >= DEEP_REVIEW_S) and len(buffer) >= 20:
                compact()
        time.sleep(TAIL_INTERVAL_S)


if __name__ == "__main__":
    main()

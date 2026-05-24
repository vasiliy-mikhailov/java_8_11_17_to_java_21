import json, os, time, urllib.request, re
from datetime import datetime, timezone

OBS_DIR = "/var/log/observe"
DIGEST = f"{OBS_DIR}/digest.jsonl"
CTX_BUDGET = 128 * 1024
OUTPUT_BUDGET = 4000
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
    "You receive a rolling trajectory of host events possibly with a prior compacted summary. "
    "Return JSON: {\"compacted_summary\":\"<paragraph compressing to ~20% of input, preserving "
    "notable patterns, sustained anomalies, drifts, recurring failures>\",\"sustained_anomalies\":[\"<fact>\"]} "
    "JSON only, no prose.")


def approx_tokens(t): return (len(t) + 1) // 2  # conservative upper bound


def ask_qwen(system, user, max_tokens=4000):
    body = {"model":"qwen3.6-27b-fp8","messages":[
            {"role":"system","content":system},{"role":"user","content":user}],
            "temperature":0.0,"max_tokens":max_tokens,"chat_template_kwargs":{"enable_thinking":False}}
    req = urllib.request.Request("http://localhost:8000/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization":"Bearer sk-ef2926520a83b7f6efac7f4dc5b049842b4b2baebfdc18b69b76220f29fdf272","Content-Type":"application/json"})
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


def compact():
    global buffer, compacted_summary, last_deep
    # Truncate buffer if needed to stay under HARD_CAP
    while buffer:
        buf_text = "\n".join(json.dumps(b)[:300] for b in buffer)
        if approx_tokens((compacted_summary or "") + buf_text) <= HARD_CAP:
            break
        buffer = buffer[len(buffer)//4:]  # drop oldest 25%
    buf_text = "\n".join(json.dumps(b)[:300] for b in buffer)
    buf_tokens = approx_tokens((compacted_summary or "") + buf_text)
    print(f"COMPACT buf={buf_tokens} tokens, samples={len(buffer)}", flush=True)
    user = "(Prior compaction:)\n" + (compacted_summary or "(none)") + "\n\n(Recent trajectory:)\n" + buf_text
    resp = ask_qwen(COMPACT_SYSTEM, user)
    compacted_summary = resp.get("compacted_summary","")
    sustained = resp.get("sustained_anomalies",[]) or []
    entry = {"t": datetime.now(timezone.utc).isoformat(), "kind":"compaction",
             "samples_compacted": len(buffer), "input_tokens": buf_tokens,
             "compacted_summary": compacted_summary, "sustained_anomalies": sustained}
    with open(DIGEST, "a") as f: f.write(json.dumps(entry)+"\n")
    print(f"COMPACT done. sustained_anomalies={sustained}", flush=True)
    buffer = buffer[-RECENT_KEEP:]
    last_deep = time.time()


def main():
    print(f"compactor_v3 (clean): skip backlog, DEEP_REVIEW={DEEP_REVIEW_S}s, HARD_CAP={HARD_CAP} tok", flush=True)
    init_offsets_at_end()
    while True:
        tail_new_lines()
        if buffer:
            per_sample_alarm()
            buf_text = "\n".join(json.dumps(b)[:300] for b in buffer)
            buf_tokens = approx_tokens((compacted_summary or "") + buf_text)
            if (buf_tokens >= COMPACT_AT or (time.time() - last_deep) >= DEEP_REVIEW_S) and len(buffer) >= 20:
                compact()
        time.sleep(TAIL_INTERVAL_S)


if __name__ == "__main__":
    main()

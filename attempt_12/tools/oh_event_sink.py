"""OpenHands → /var/log/observe/openhands.jsonl JSONL sink.

Vector-shape rows so ff #7's compactor can tail this stream alongside
host_metrics.jsonl / docker.jsonl / app_logs.jsonl with no special-case parsing.

Schema:
  timestamp  RFC3339 Z-suffixed (matches Vector)
  host       socket.gethostname()
  source_type "openhands"          # mirrors Vector's source_type tag
  conv_id    str(conversation.id)
  slug       caller-supplied stage label (or None)
  event_type "MessageEvent" | "ActionEvent" | "ObservationEvent" | ...
  event_id   event.id
  source     "user" | "agent" | "environment"
  tool_name  str | None
  iter       running index per conversation
  summary    short human-readable label (≤200 chars)

We only flush short summaries — never raw bytes — so this stream is safe to
ship to a length-bounded compactor. Heavy detail stays in the trajectory.
"""
import json, os, socket, time
from datetime import datetime, timezone
from threading import Lock

DEFAULT_SINK = "/var/log/observe/openhands.jsonl"
_HOST = socket.gethostname()
_LOCK = Lock()  # multiple callbacks may share one file


def _iso_now():
    # RFC3339 with Z, microsecond precision — matches Vector's `timestamp`
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _summary(ev):
    """One-line human-readable label per event type, capped at 200 chars."""
    et = type(ev).__name__
    if et == "MessageEvent":
        # Concatenate text content snippets
        try:
            parts = []
            for c in ev.llm_message.content:
                t = getattr(c, "text", "") or ""
                if t: parts.append(t)
            return (" ".join(parts).replace("\n", " "))[:200]
        except Exception:
            return ""
    if et == "ActionEvent":
        s = getattr(ev, "summary", None) or ""
        thought = getattr(ev, "thought", "") or ""
        tool = getattr(ev, "tool_name", "") or ""
        return f"[{tool}] {s or thought}".strip()[:200]
    if et == "ObservationEvent":
        tool = getattr(ev, "tool_name", "") or ""
        try:
            o = ev.observation
            txt = (getattr(o, "content", None) or getattr(o, "output", None) or str(o))
            if not isinstance(txt, str): txt = json.dumps(txt, default=str)
        except Exception:
            txt = ""
        return f"[{tool}] {txt.replace(chr(10),' ')}".strip()[:200]
    return ""


def make_callback(conv_id, slug=None, sink_path=DEFAULT_SINK):
    """Build a Conversation callback that appends one JSONL row per Event."""
    counter = {"i": 0}

    def _cb(ev):
        with _LOCK:
            counter["i"] += 1
            row = {
                "timestamp": _iso_now(),
                "host": _HOST,
                "source_type": "openhands",
                "conv_id": str(conv_id),
                "slug": slug,
                "event_type": type(ev).__name__,
                "event_id": getattr(ev, "id", None),
                "source": getattr(ev, "source", None),
                "tool_name": getattr(ev, "tool_name", None),
                "iter": counter["i"],
                "summary": _summary(ev),
            }
            try:
                with open(sink_path, "a") as f:
                    f.write(json.dumps(row, default=str) + "\n")
            except Exception as e:
                # never let the sink kill the conversation
                print(f"[oh_event_sink] write failed: {e}", flush=True)
    return _cb

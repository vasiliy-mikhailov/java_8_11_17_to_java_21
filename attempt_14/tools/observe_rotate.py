#!/usr/bin/env python3
"""Frog's-eye sink rotation (P10): keep observability storage from filling the disk and crashing
the digester. Two layers, both truncate-in-place when over cap (frees blocks; the writer keeps
its fd; the digester has already compacted older events into the digest):

  1. Vector's JSONL sinks under /var/log/observe/.
  2. The raw Docker container json-logs Vector tails (incl Vector's own obs-vector container) —
     Docker's default json-file driver has NO rotation, so one unbounded container log can hit
     tens of GB and fill the disk.

Root-owned paths are truncated via a root busybox container (the project's docker-as-root
pattern; the agent has no passwordless sudo). Loops forever — run under a keepalive.
NOTE: the permanent fix for layer 2 is docker daemon log-opts (max-size/max-file) on a
maintenance restart; this janitor bounds it non-disruptively in the meantime."""
import os, subprocess, time
OBS = "/var/log/observe"
SINK_CAP = 600 * 1024**2          # /var/log/observe/*.jsonl cap
DLOG_CAP_MB = 1024                 # docker container json-log cap (MB)
INTERVAL = 300
SINKS = ["docker.jsonl", "host_metrics.jsonl", "app_logs.jsonl", "openhands.jsonl"]
DOCKER_CONTAINERS = "/var/lib/docker/containers"

def rotate_sink(name):
    p = f"{OBS}/{name}"
    try:
        sz = os.path.getsize(p)
    except OSError:
        return None
    if sz <= SINK_CAP:
        return None
    if os.stat(p).st_uid == 0:
        subprocess.run(["docker", "run", "--rm", "-v", f"{OBS}:{OBS}", "busybox", "sh", "-c", f": > {p}"],
                       capture_output=True, timeout=120)
    else:
        subprocess.run(f": > {p}", shell=True, capture_output=True, timeout=120)
    return sz

def rotate_docker_logs():
    # find + truncate over-cap container json-logs (root-owned) via one root busybox pass
    script = (f'for f in {DOCKER_CONTAINERS}/*/*-json.log; do '
              f'[ -f "$f" ] || continue; '
              f'sz=$(stat -c %s "$f" 2>/dev/null || echo 0); '
              f'if [ "$sz" -gt $(({DLOG_CAP_MB}*1024*1024)) ]; then : > "$f"; echo "truncated $f was=${{sz}}B"; fi; done')
    r = subprocess.run(["docker", "run", "--rm", "-v", f"{DOCKER_CONTAINERS}:{DOCKER_CONTAINERS}", "busybox", "sh", "-c", script],
                       capture_output=True, text=True, timeout=180)
    return [l for l in r.stdout.splitlines() if l.strip()]

def main():
    while True:
        for s in SINKS:
            r = rotate_sink(s)
            if r:
                print(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] sink {s}: truncated, was {r//1048576}MB", flush=True)
        for line in rotate_docker_logs():
            print(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] docker-log {line}", flush=True)
        time.sleep(INTERVAL)

if __name__ == "__main__":
    main()

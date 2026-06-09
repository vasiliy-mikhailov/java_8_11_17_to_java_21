#!/usr/bin/env python3
"""Discover FRESH Gradle repos (build.gradle / build.gradle.kts) at a given Java
version via gh CLI code-search, deduped against everything we already have (Maven
+ Gradle). Writes /tmp/gradle_j{jv}_fresh.txt. Java-version markers cover both the
modern toolchain DSL (JavaLanguageVersion.of(N)) and source/targetCompatibility
(JavaVersion.VERSION_N) in Groovy and Kotlin DSL."""
import os, json, time, subprocess, glob, sys
A = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"
JVS = [int(x) for x in (sys.argv[1].split(",") if len(sys.argv) > 1 else ["17", "21"])]

# ---- KNOWN set: same sources as the Maven discovery + any prior Gradle finds ----
known = set()
def add(it):
    for r in it:
        if isinstance(r, str) and "/" in r: known.add(r.strip())
for p in [f"{A}/dataset-repos.json"]:
    try: add(json.load(open(p)))
    except Exception: pass
try: add(x.get("repo") for x in json.load(open(f"{A}/dataset-shas.json")))
except Exception: pass
try:
    d = json.load(open(f"{A}/corpus/attempt_db.json"))
    for sect in ("baselines", "repo_pool_by_jv"):
        for k, v in d.get(sect, {}).items(): add(v.keys() if isinstance(v, dict) else v)
    add((t.get("repo") if isinstance(t, dict) else None) for t in d.get("trajectories", []))
except Exception: pass
for p in glob.glob("/home/vmihaylov/*dig*.json"):
    try:
        d = json.load(open(p)); add((x.get("repo") if isinstance(x, dict) else x) for x in (d if isinstance(d, list) else d.values()))
    except Exception: pass
for p in glob.glob("/tmp/j17*.txt") + glob.glob("/tmp/j21*.txt") + glob.glob("/tmp/gradle_*.txt"):
    try:
        for line in open(p):
            if "/" in line: known.add(line.strip())
    except Exception: pass
known = {r for r in known if r}
print("KNOWN repos (dedup target):", len(known), flush=True)

FILES = ['filename:build.gradle', 'filename:build.gradle.kts']
def markers(jv):
    return [f'"JavaLanguageVersion.of({jv})"', f'"JavaVersion.VERSION_{jv}"']

def gh_search(q, page):
    try:
        out = subprocess.run(["gh","api","-X","GET","search/code","-f",f"q={q}","-f","per_page=100","-f",f"page={page}",
                              "--jq",".items[].repository.full_name"], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return "retry" if "rate limit" in (out.stderr or "").lower() else None
        return [l for l in out.stdout.splitlines() if l.strip()]
    except subprocess.TimeoutExpired:
        return None

for jv in JVS:
    res = set()
    for fn in FILES:
        for mk in markers(jv):
            q = f"{fn} {mk}"
            page = 1
            while page <= 8:
                r = gh_search(q, page)
                if r == "retry":
                    print("  rate-limited, sleep 60", flush=True); time.sleep(60); continue
                if not r: break
                res.update(r); page += 1; time.sleep(2.2)
                if len(r) < 100: break
            print("J%d gradle %-40s unique=%d" % (jv, q[:40], len(res)), flush=True)
    fresh = sorted(res - known)
    out = f"/tmp/gradle_j{jv}_fresh.txt"
    open(out, "w").write("\n".join(fresh) + ("\n" if fresh else ""))
    print("J%d GRADLE FRESH (new unique): %d -> %s" % (jv, len(fresh), out), flush=True)

#!/usr/bin/env python3
"""Discover FRESH J17/J21 Maven repos via gh CLI code-search, deduped against
everything we already have. Writes /tmp/j17_fresh3.txt and /tmp/j21_fresh3.txt."""
import os, json, time, subprocess, glob
A = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"

# ---- build the KNOWN set from every source ----
known = set()
def add_repos(it):
    for r in it:
        if isinstance(r, str) and "/" in r: known.add(r)
# pool
for p in [f"{A}/dataset-repos.json"]:
    try: add_repos(json.load(open(p)))
    except Exception as e: print("skip", p, e)
# iter-db shas
try:
    add_repos(x.get("repo") for x in json.load(open(f"{A}/dataset-shas.json")))
except Exception as e: print("skip shas", e)
# attempt_db baselines + pools
try:
    d = json.load(open(f"{A}/corpus/attempt_db.json"))
    for sect in ("baselines", "repo_pool_by_jv"):
        for k, v in d.get(sect, {}).items():
            add_repos(v.keys() if isinstance(v, dict) else v)
    add_repos((t.get("repo") if isinstance(t, dict) else None) for t in d.get("trajectories", []))
except Exception as e: print("skip attempt_db", e)
# dig jsons
for p in glob.glob("/home/vmihaylov/*dig*.json"):
    try:
        d = json.load(open(p))
        add_repos((x.get("repo") if isinstance(x, dict) else x) for x in (d if isinstance(d, list) else d.values()))
    except Exception: pass
# existing candidate repos-files
for p in glob.glob("/tmp/j17*.txt") + glob.glob("/tmp/j21*.txt"):
    try:
        for line in open(p):
            r = line.strip()
            if "/" in r: known.add(r)
    except Exception: pass
known = {r for r in known if r}
print("KNOWN repos (dedup target):", len(known), flush=True)

# ---- search via gh CLI ----
PRE = "filename:pom.xml "
Q = {17: ['"<java.version>17<"', '"<maven.compiler.source>17<"', '"<maven.compiler.release>17<"', '"<maven.compiler.target>17<"'],
     21: ['"<java.version>21<"', '"<maven.compiler.source>21<"', '"<maven.compiler.release>21<"', '"<maven.compiler.target>21<"']}

def gh_search(q, page):
    try:
        out = subprocess.run(["gh","api","-X","GET","search/code","-f",f"q={q}","-f","per_page=100","-f",f"page={page}",
                              "--jq",".items[].repository.full_name"], capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            if "rate limit" in (out.stderr or "").lower(): return "retry"
            return None
        return [l for l in out.stdout.splitlines() if l.strip()]
    except subprocess.TimeoutExpired:
        return None

res = {17: set(), 21: set()}
for jv in (17, 21):
    for q in Q[jv]:
        full = PRE + q
        page = 1
        while page <= 10:
            r = gh_search(full, page)
            if r == "retry":
                print("  rate-limited, sleep 60", flush=True); time.sleep(60); continue
            if not r: break
            res[jv].update(r)
            page += 1
            time.sleep(2.2)   # ~27/min < 30 search cap
            if len(r) < 100: break
        print("J%d  %-44s unique=%d" % (jv, q[:44], len(res[jv])), flush=True)

for jv in (17, 21):
    fresh = sorted(res[jv] - known)
    out = f"/tmp/j{jv}_fresh3.txt"
    open(out, "w").write("\n".join(fresh) + ("\n" if fresh else ""))
    print("J%d FRESH (new unique): %d -> %s" % (jv, len(fresh), out), flush=True)

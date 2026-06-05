#!/usr/bin/env python3
"""Fast GitHub code-search for FRESH J8/J11 Maven repos (beyond our existing pool).
Outputs /tmp/fresh_gh_repos.json = {"8":{repo:null,...},"11":{repo:null,...}} of repos
NOT already in dataset-repos.json or the lineage backlog, for verify_green2.py --extra.
Token read from $GITHUB_TOKEN (pass via:  GITHUB_TOKEN=$(gh auth token) python3 ...)."""
import os, json, time, urllib.request, urllib.parse, urllib.error

A = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
H = {"Accept": "application/vnd.github+json", "User-Agent": "claude-disco"}
if TOKEN:
    H["Authorization"] = "Bearer " + TOKEN
# NOTE: GitHub code-search zeroes out when language:Java is combined with the full
# "<tag>val</tag>" phrase (angle-bracket tokenization). Drop language:Java and anchor
# the value with a trailing "<" (close-tag start) or use the "1.8" form.
PRE = "filename:pom.xml "
Q = {8: ['"<java.version>1.8"', '"<java.version>8<"', '"<maven.compiler.source>1.8"',
         '"<maven.compiler.source>8<"', '"<maven.compiler.release>8<"'],
     11: ['"<java.version>11<"', '"<maven.compiler.source>11<"',
          '"<maven.compiler.release>11<"', '"<maven.compiler.target>11<"']}

def search(q, page):
    url = "https://api.github.com/search/code?q=" + urllib.parse.quote(q) + "&per_page=100&page=%d" % page
    req = urllib.request.Request(url, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            print("  rate-limited, sleep 60", flush=True); time.sleep(60); return "retry"
        print("  http", e.code, flush=True); return None
    except Exception as ex:
        print("  err", ex, flush=True); return None

pool = set(json.load(open(A + "/dataset-repos.json")))
cand = json.load(open("/tmp/cand_8_11.json"))
known = pool | set(cand["8"]) | set(cand["11"])
res = {8: set(), 11: set()}
for jv in (8, 11):
    for q in Q[jv]:
        full = PRE + q
        page = 1
        while page <= 10:
            d = search(full, page)
            if d == "retry":
                continue
            if not d:
                break
            items = d.get("items", [])
            if not items:
                break
            for it in items:
                r = (it.get("repository") or {}).get("full_name")
                if r:
                    res[jv].add(r)
            page += 1
            time.sleep(2.2)            # ~27 req/min < 30 code-search cap
            if len(items) < 100:
                break
        print("J%d  %-46s unique=%d" % (jv, q[:46], len(res[jv])), flush=True)

fresh = {str(jv): {r: None for r in sorted(res[jv]) if r not in known} for jv in (8, 11)}
json.dump(fresh, open("/tmp/fresh_gh_repos.json", "w"))
print("FRESH (not already known): J8=%d J11=%d  | excluded %d already-known"
      % (len(fresh["8"]), len(fresh["11"]), len(known)), flush=True)

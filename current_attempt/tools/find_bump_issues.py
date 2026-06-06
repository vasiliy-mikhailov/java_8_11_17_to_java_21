#!/usr/bin/env python3
# Find OPEN GitHub issues asking to bump/upgrade the Java version (title-matched, Java repos),
# deduped by repo and ranked by stars. Output a clean actionable list.
import subprocess, json, time, collections
QUERIES = [
    '"upgrade java" in:title',
    '"bump java" in:title',
    '"migrate to java" in:title',
    '"update java version" in:title',
    '"upgrade to java 17" in:title',
    '"upgrade to java 21" in:title',
    '"upgrade to java 11" in:title',
    '"migrate to java 17" in:title',
    '"java version upgrade" in:title',
    '"upgrade jdk" in:title',
]
seen = {}   # url -> item
for q in QUERIES:
    full = q + " state:open type:issue language:java"
    for page in (1, 2):
        r = subprocess.run(["gh", "api", "-X", "GET", "search/issues",
                            "-f", "q=" + full, "-f", "per_page=50", "-f", "page=" + str(page)],
                           capture_output=True, text=True)
        try: items = json.loads(r.stdout).get("items", [])
        except Exception: items = []
        if not items: break
        for it in items:
            seen[it["html_url"]] = {
                "repo": it["repository_url"].split("/repos/")[-1],
                "title": it["title"], "url": it["html_url"], "created": it["created_at"][:10],
            }
        time.sleep(2.2)
# dedup by repo (keep newest issue per repo)
byrepo = {}
for it in seen.values():
    cur = byrepo.get(it["repo"])
    if cur is None or it["created"] > cur["created"]:
        byrepo[it["repo"]] = it
# stars for ranking
repos = list(byrepo)
stars = {}
for i in range(0, len(repos), 50):
    batch = repos[i:i + 50]; parts = []
    for j, rp in enumerate(batch):
        o, n = rp.split("/", 1); o = o.replace('"', '\\"'); n = n.replace('"', '\\"')
        parts.append(f'a{j}: repository(owner: "{o}", name: "{n}") {{ stargazerCount }}')
    rr = subprocess.run(["gh", "api", "graphql", "-f", "query=query { " + " ".join(parts) + " }"],
                        capture_output=True, text=True)
    try: data = json.loads(rr.stdout).get("data") or {}
    except Exception: data = {}
    for j, rp in enumerate(batch):
        nd = data.get(f"a{j}"); stars[rp] = nd["stargazerCount"] if nd and nd.get("stargazerCount") is not None else -1
rows = sorted(byrepo.values(), key=lambda it: stars.get(it["repo"], -1), reverse=True)
print(f"=== {len(rows)} repos with an OPEN Java-bump request (deduped, ranked by stars) ===\n")
for it in rows:
    print(f"{stars.get(it['repo'],-1):6}  {it['repo']:42}  {it['created']}  {it['title'][:54]}")
    print(f"        {it['url']}")
json.dump(rows, open("/home/vmihaylov/bump_issues.json", "w"), indent=1)
print(f"\n-> /home/vmihaylov/bump_issues.json ({len(rows)} repos)")

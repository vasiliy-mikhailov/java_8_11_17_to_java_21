#!/usr/bin/env python3
"""Rank the UNTRIED fresh J11 repos by GitHub stars, so we verify popular/maintained
projects (real unit tests) instead of random alphabetical ones. Outputs /tmp/popular_j11.json
(top N by stars) for verify_green2.py --extra. Token from $GITHUB_TOKEN."""
import os, json, time, urllib.request, urllib.error
TOKEN = os.environ["GITHUB_TOKEN"]
H = {"Accept": "application/vnd.github+json", "User-Agent": "x", "Authorization": "Bearer " + TOKEN}
TOPN = int(os.environ.get("TOPN", "600"))

fresh = json.load(open("/tmp/fresh_gh_repos.json"))["11"]      # dict repo->null
tried = set()
for lg in ("/tmp/vg2_j11.log", "/tmp/vg2_j11b.log", "/tmp/vg2_mineF.log"):
    if os.path.exists(lg):
        for ln in open(lg):
            p = ln.split()
            if ln.startswith("GREEN J11") and len(p) >= 5:
                tried.add(p[3])
            elif ln.startswith("MISS J11") and len(p) >= 3:
                tried.add(p[2])
cands = [r for r in fresh if r not in tried]
print("untried fresh J11 to rank:", len(cands), flush=True)

stars = {}
for i, r in enumerate(cands):
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://api.github.com/repos/" + r, headers=H), timeout=20).read())
        stars[r] = d.get("stargazers_count", 0)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            time.sleep(30)
            continue
        stars[r] = -1
    except Exception:
        stars[r] = -1
    if i % 250 == 0:
        print(i, "/", len(cands), "ranked", flush=True)
    time.sleep(0.05)

top = sorted([r for r in stars if stars[r] > 0], key=lambda r: -stars[r])[:TOPN]
json.dump({"8": {}, "11": {r: None for r in top}}, open("/tmp/popular_j11.json", "w"))
print("top-10 by stars:", [(r, stars[r]) for r in top[:10]], flush=True)
print("wrote /tmp/popular_j11.json with", len(top), "repos (stars>0)", flush=True)

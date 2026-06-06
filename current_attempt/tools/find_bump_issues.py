#!/usr/bin/env python3
# P12 request feed: OPEN GitHub issues asking to bump the Java/JDK version, enriched with the
# triage signals P12's contract requires — stars, maintenance (pushedAt/archived), and a
# genuinely-unsatisfied check (current Java version via the root pom vs the requested target).
import subprocess, json, time, re, base64, datetime

QUERIES = [
    '"upgrade java" in:title', '"bump java" in:title', '"migrate to java" in:title',
    '"update java version" in:title', '"upgrade to java 17" in:title', '"upgrade to java 21" in:title',
    '"upgrade to java 11" in:title', '"migrate to java 17" in:title', '"java version upgrade" in:title',
    '"upgrade jdk" in:title', '"upgrade to jdk" in:title',
]
GOOD = re.compile(r"(upgrade|migrat|update|move|bump).{0,25}(to\s+)?(java|jdk)\s*\d{1,2}\b"
                  r"|(java|jdk)\s*\d{1,2}\b.{0,20}(upgrade|support|migration)"
                  r"|upgrade java version|latest lts version", re.I)
BAD = re.compile(r"connector|mysql|\.time|jzlib|\basm\b|codegen|driver|-java\b|javassist|javaparser|javadoc|deflate", re.I)

def gh(*a):
    return subprocess.run(["gh", "api"] + list(a), capture_output=True, text=True)

def detect_jv(text):
    vs = []
    for m in re.finditer(r"<(?:maven\.compiler\.(?:release|source|target)|java\.version|release|source)>([0-9][0-9.]*)", text):
        num = m.group(1)
        try:
            v = int(num[2:].split(".")[0]) if num.startswith("1.") and len(num) > 2 else int(num.split(".")[0])
        except ValueError:
            continue
        if v in (8, 11, 17, 21, 25):
            vs.append(v)
    return max(vs) if vs else None

def target_from_title(t):
    nums = [int(x) for x in re.findall(r"(?:java|jdk)\s*([0-9]{1,2})", t, re.I) if 8 <= int(x) <= 25]
    return max(nums) if nums else None

# 1. search -> dedup by repo, keep only genuine bump titles
seen = {}
for q in QUERIES:
    for page in (1, 2):
        r = gh("-X", "GET", "search/issues", "-f", "q=" + q + " state:open type:issue language:java",
               "-f", "per_page=50", "-f", "page=" + str(page))
        try: items = json.loads(r.stdout).get("items", [])
        except Exception: items = []
        if not items: break
        for it in items:
            seen[it["html_url"]] = {"repo": it["repository_url"].split("/repos/")[-1], "title": it["title"],
                                    "url": it["html_url"], "created": it["created_at"][:10]}
        time.sleep(2.2)
byrepo = {}
for it in seen.values():
    if not GOOD.search(it["title"]) or BAD.search(it["title"]):
        continue
    cur = byrepo.get(it["repo"])
    if cur is None or it["created"] > cur["created"]:
        byrepo[it["repo"]] = it
print("genuine bump requests:", len(byrepo), flush=True)

# 2. stars + maintenance via GraphQL
meta = {}
repos = list(byrepo)
for i in range(0, len(repos), 50):
    batch = repos[i:i + 50]; parts = []
    for j, rp in enumerate(batch):
        o, n = rp.split("/", 1); o = o.replace('"', '\\"'); n = n.replace('"', '\\"')
        parts.append(f'a{j}: repository(owner: "{o}", name: "{n}") {{ stargazerCount pushedAt isArchived isDisabled }}')
    rr = gh("graphql", "-f", "query=query { " + " ".join(parts) + " }")
    try: data = json.loads(rr.stdout).get("data") or {}
    except Exception: data = {}
    for j, rp in enumerate(batch):
        meta[rp] = data.get(f"a{j}") or {}

# 3. genuinely-unsatisfied check via root pom + requested target
now = datetime.datetime.now(datetime.timezone.utc)
out = []
for rp, it in byrepo.items():
    m = meta.get(rp, {})
    stars = m.get("stargazerCount", -1)
    pushed = m.get("pushedAt")
    archived = bool(m.get("isArchived")) or bool(m.get("isDisabled"))
    maintained = bool((not archived) and pushed and
                      (now - datetime.datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days <= 730)
    target = target_from_title(it["title"])
    cur = None
    pr = gh("-X", "GET", f"repos/{rp}/contents/pom.xml")
    try:
        c = json.loads(pr.stdout)
        if isinstance(c, dict) and c.get("content"):
            cur = detect_jv(base64.b64decode(c["content"]).decode("utf-8", "ignore"))
    except Exception:
        pass
    if target and cur is not None:
        status = "satisfied(stale-open)" if cur >= target else "unsatisfied"
    elif cur is None:
        status = "unknown(no-root-pom)"
    else:
        status = "unsatisfied(no-target)"
    out.append({**it, "stars": stars, "pushed_at": (pushed or "")[:10], "archived": archived,
                "maintained": maintained, "current_jv": cur, "target_jv": target, "status": status})
    time.sleep(0.15)

keep = [r for r in out if r["maintained"] and not r["status"].startswith("satisfied")]
keep.sort(key=lambda r: r["stars"], reverse=True)
json.dump(keep, open("/home/vmihaylov/bump_issues.json", "w"), indent=1)
json.dump(out, open("/home/vmihaylov/bump_issues_all.json", "w"), indent=1)
sat = sum(1 for r in out if r["status"].startswith("satisfied"))
unm = sum(1 for r in out if not r["maintained"])
print(f"\n{len(out)} genuine -> kept {len(keep)} (maintained & unsatisfied) | dropped {sat} stale-open + {unm} unmaintained/archived")
for r in keep[:20]:
    print(f"  {r['stars']:6}*  {r['repo']:38} cur={str(r['current_jv']):4} ->{str(r['target_jv']):4} {r['status']:20} {r['title'][:36]}")

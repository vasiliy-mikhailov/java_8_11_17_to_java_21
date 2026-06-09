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

def _norm_jv(num):
    num = (num or "").strip()
    try:
        return int(num[2:].split(".")[0]) if num.startswith("1.") and len(num) > 2 else int(num.split(".")[0])
    except ValueError:
        return None


def detect_jv(text):
    # The real build floor is the MAX of: compiler source/target/release, java.version, AND the
    # maven-enforcer requireJavaVersion lower bound — projects routinely keep compiler target low
    # (bytecode compat) while requiring a newer JDK to build (cassandra-reaper: target 8 but enforcer
    # build.jdk.minimum=11). Reading only compiler tags mis-routes such requests (phantom extra hop).
    props = dict(re.findall(r"<([a-zA-Z0-9_.\-]+)>([^<>${}]*)</\1>", text))  # for ${...} resolution

    def resolve(s):
        for _ in range(4):
            m = re.search(r"\$\{([^}]+)\}", s)
            if not m:
                break
            s = s.replace(m.group(0), props.get(m.group(1), ""))
        return s

    vs = []
    for m in re.finditer(r"<(?:maven\.compiler\.(?:release|source|target)|java\.version|release|source)>([0-9][0-9.]*)", text):
        v = _norm_jv(m.group(1))
        if v in (8, 11, 17, 21, 25):
            vs.append(v)
    # enforcer requireJavaVersion lower bound (e.g. [11,) or [${build.jdk.minimum},) or 1.11)
    for m in re.finditer(r"<requireJavaVersion>\s*<version>\s*\[?\s*([^,)\]\s<]+)", text):
        v = _norm_jv(resolve(m.group(1)))
        if v in (8, 11, 17, 21, 25):
            vs.append(v)
    return max(vs) if vs else None

def detect_jv_gradle(text):
    # Same floor logic as sample_shas.detect_jv_gradle, over the fetched build-file text.
    vs = []
    vs += [int(m) for m in re.findall(r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)", text)]
    vs += [8 for _ in re.findall(r"VERSION_1_8", text)]
    vs += [int(m) for m in re.findall(r"VERSION_(\d+)\b", text)]
    vs += [int(m) for m in re.findall(r"(?:source|target)Compatibility\s*=?\s*[\"\']?(?:1\.)?(\d{1,2})\b", text)]
    vs += [int(m) for m in re.findall(r"languageVersion\s*=\s*[\"\']?(\d{1,2})\b", text)]
    vs += [int(m) for m in re.findall(r"jvmToolchain\(\s*(\d{1,2})\s*\)", text)]
    vs += [int(m) for m in re.findall(r"JavaVersion\.toVersion\(\s*[\"\']?(?:1\.)?(\d{1,2})", text)]
    vs += [int(m) for m in re.findall(r"options\.release\D{0,8}(\d{1,2})", text)]
    vs += [int(m) for m in re.findall(r"\brelease\.set\(\s*(\d{1,2})", text)]
    # gradle.properties / ext key=value: javaVersion=17, java.version=17, jdkVersion=17, jvmTarget=17
    vs += [int(m) for m in re.findall(r"(?:javaVersion|java\.version|jdkVersion|jvmTarget|javaLanguageVersion)\s*=\s*[\"\']?(?:1\.)?(\d{1,2})\b", text, re.I)]
    vs = [v for v in vs if v in (8, 11, 17, 21, 25)]
    return max(vs) if vs else None


def _fetch_text(rp, path):
    r = gh("-X", "GET", f"repos/{rp}/contents/{path}")
    try:
        c = json.loads(r.stdout)
        if isinstance(c, dict) and c.get("content"):
            return base64.b64decode(c["content"]).decode("utf-8", "ignore")
    except Exception:
        pass
    return None


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
    cur = None; build_tool = None
    pom = _fetch_text(rp, "pom.xml")
    if pom is not None:
        build_tool = "maven"
        cur = detect_jv(pom)
    else:
        # Gradle: the Java version may live in the root build file, gradle.properties,
        # an Android app/ module, or a buildSrc convention plugin -- gather all cheap spots.
        gtxt = ""
        for gf in ("build.gradle", "build.gradle.kts", "gradle.properties",
                   "app/build.gradle", "app/build.gradle.kts",
                   "buildSrc/build.gradle", "buildSrc/build.gradle.kts"):
            t = _fetch_text(rp, gf)
            if t is not None:
                build_tool = "gradle"
                gtxt += t + "\n"
        if build_tool == "gradle":
            cur = detect_jv_gradle(gtxt)
    if target and cur is not None:
        status = "satisfied(stale-open)" if cur >= target else "unsatisfied"
    elif cur is None:
        status = "unknown(no-build-version)" if build_tool else "unknown(no-build-file)"
    else:
        status = "unsatisfied(no-target)"
    out.append({**it, "stars": stars, "pushed_at": (pushed or "")[:10], "archived": archived,
                "maintained": maintained, "build_tool": build_tool, "current_jv": cur,
                "target_jv": target, "status": status})
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

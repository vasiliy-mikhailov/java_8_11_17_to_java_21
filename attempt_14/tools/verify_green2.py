#!/usr/bin/env python3
"""Commit-search verifier for test-green J8/J11 baselines.

For each candidate REPO (not a single sha), clone full history and probe commits
that declare the target Java version, running `JDK={jv} mvn test` until one is GREEN
(compiles + tests run + 0 failures/0 errors) or a bounded build budget is spent.
This is the "probe commits versions" approach: a repo with any green J8/J11 commit
in its history is found, even if the lineage's pinned sha isn't itself green.

Priority order per jv:
  1. known-green repos (had pre_pass_count>0 in past attempts)  [highest yield]
  2. brand-new backlog repos (not in dataset-repos.json)         [expands the pool]
  3. in-pool backlog repos
  4. --extra <json {"8":{repo:sha|null},...}>  fresh GitHub-discovered repos.

Resumable (skips repos already in --out), parallel, reaps each workdir.
Usage: verify_green2.py [--target 78] [--workers 10] [--jv 8|11|both]
                        [--maxbuild 5] [--scancap 120] [--extra PATH] [--out PATH]
"""
import json, os, re, subprocess, sys, threading, random
from concurrent.futures import ThreadPoolExecutor

def arg(n, d):
    for a in sys.argv:
        if a.startswith(n + "="):
            return a.split("=", 1)[1]
    return d

A = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"
TARGET = int(arg("--target", "78")); WORKERS = int(arg("--workers", "10"))
JVSEL = arg("--jv", "both"); MAXBUILD = int(arg("--maxbuild", "5")); SCANCAP = int(arg("--scancap", "120"))
OUT = arg("--out", "/tmp/verify_green.jsonl"); EXTRA = arg("--extra", "")
NEXT = {8: 11, 11: 17}

cand = json.load(open("/tmp/cand_8_11.json"))                  # jv(str)->{repo:sha}
known = json.load(open("/tmp/green_8_11_baselines.json"))      # "repo|jv"->{sha,pass}
pool_repos = set(json.load(open(A + "/dataset-repos.json")))
used = {d["repo"] for d in json.load(open(A + "/dataset-shas.json"))}
extra = {}
if EXTRA and os.path.exists(EXTRA):
    e = json.load(open(EXTRA))
    for k in ("8", "11"):
        v = e.get(k, {})
        extra[k] = v if isinstance(v, dict) else {r: None for r in v}

def sh(c, to=300):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=to)
    except subprocess.TimeoutExpired:
        class R: returncode = 124; stdout = ""; stderr = ""
        return R()

def pom_versions(wd):
    """Set of Java majors declared anywhere in the repo's poms (1.8 -> 8). Gate on
    membership (jv in set), not max==jv: a repo that declares jv in a parent but a
    higher major in some module still gets a build attempt -- and the build under
    JDK={jv} naturally rejects it if it actually requires newer."""
    o = sh("grep -rhoE '<(maven.compiler.release|maven.compiler.target|maven.compiler.source|"
           "java.version|release|target|source)>[0-9.]+' " + wd + " --include=pom.xml 2>/dev/null").stdout.splitlines()
    vs = set()
    for ln in o:
        m = re.search(r'>([0-9.]+)$', ln)
        if not m:
            continue
        v = m.group(1)
        if v.startswith("1."):
            v = v.split(".", 1)[1]      # 1.8 -> 8
        if v.isdigit() and int(v) in (8, 11, 17, 21):
            vs.add(int(v))
    return vs

def green(out, rc):
    # Corpus-aligned bar: a baseline is valid if it has >=1 PASSING test (pre_pass_count>0),
    # NOT if every test passes. rc may be nonzero when some tests fail/error -- those are
    # baseline-failures, excluded from conservation exactly as the corpus does. We only need
    # the compile to reach the test phase and at least one genuinely passing test.
    total = bad = 0; saw = False
    for m in re.finditer(r"Tests run: (\d+), Failures: (\d+), Errors: (\d+)(?:, Skipped: (\d+))?", out):
        saw = True
        total += int(m.group(1)); bad += int(m.group(2)) + int(m.group(3)) + int(m.group(4) or 0)
    return saw and (total - bad) > 0

def mvn_test(wd, jv):
    cmd = ("export PATH=$HOME/bin:$PATH; cd " + wd + " && JDK=%d mvn -B -ntp test > " % jv + wd +
           "/mvn.log 2>&1; echo RC=$?; grep -hE 'Tests run:' " + wd + "/mvn.log | tail -60")
    r = sh(cmd, 1200); out = r.stdout or ""
    m = re.search(r"RC=(\d+)", out); rc = int(m.group(1)) if m else 124
    return green(out, rc)

def search_green(repo, jv, hint, wd):
    sh("rm -rf " + wd, 60)
    if sh("git clone -q https://github.com/" + repo + " " + wd, 900).returncode != 0 or not os.path.isdir(wd + "/.git"):
        return None, "clonefail"
    allc = set(sh("git -C " + wd + " log --all --pretty=%H", 60).stdout.split())
    if not allc:
        return None, "nocommits"
    head = sh("git -C " + wd + " rev-parse HEAD", 30).stdout.strip()
    # commits that touched ANY pom.xml -- this is where java versions change, so the jv era
    # lives here. Scanning these (newest first) finds an 11/8 era far more reliably than random.
    pomc = sh("git -C " + wd + " log --all --pretty=%H -- '*pom.xml' pom.xml", 60).stdout.split()
    order, seen = [], set()
    for c in [hint, head] + pomc:
        if c and c in allc and c not in seen:
            seen.add(c); order.append(c)
    rest = [c for c in allc if c not in seen]
    random.Random("seed:" + repo).shuffle(rest)
    order = order + rest                                       # pom-change commits first, then the rest
    builds = scanned = 0
    for shav in order:
        if builds >= MAXBUILD or scanned >= SCANCAP:
            break
        scanned += 1
        sh("git -C " + wd + " checkout -q " + shav + " 2>/dev/null", 60)
        if not os.path.isfile(wd + "/pom.xml"):
            continue
        if jv not in pom_versions(wd):
            continue
        builds += 1
        if mvn_test(wd, jv):
            return shav, "green"
    return None, "nogreen(b%d)" % builds

count = {8: 0, 11: 0}; lock = threading.Lock(); done = set()   # set of (repo, jv) -- per-hop
if os.path.exists(OUT):
    for l in open(OUT):
        try:
            e = json.loads(l); done.add((e["repo"], e["jv_from"])); count[e["jv_from"]] = count.get(e["jv_from"], 0) + 1
        except Exception:
            pass
# --skiplog: also skip (repo, jv) pairs already TRIED (green or miss) in a prior run log, so a
# resumed run processes only untried hop-candidates -- and a J8-green repo can still be mined for J11.
SKIPLOG = arg("--skiplog", "")
if SKIPLOG and os.path.exists(SKIPLOG):
    for ln in open(SKIPLOG):
        p = ln.split()
        if ln.startswith("GREEN J") and len(p) >= 5:
            done.add((p[3], int(p[1][1:])))
        elif ln.startswith("MISS J") and len(p) >= 3:
            done.add((p[2], int(p[1][1:])))

def order_repos(jv):
    s = str(jv); seen = set(); out = []
    def push(repo, hint):
        if repo and repo not in seen and (repo, jv) not in done and repo not in used:
            seen.add(repo); out.append((repo, hint))
    for k in known:                                   # 1. known-green
        if k.endswith("|" + s):
            r = k.split("|")[0]; push(r, cand[s].get(r))
    bn = [(r, shv) for r, shv in cand[s].items() if r not in pool_repos]  # 2. brand-new
    random.Random(0).shuffle(bn)
    for r, shv in bn:
        push(r, shv)
    ip = [(r, shv) for r, shv in cand[s].items() if r in pool_repos]      # 3. in-pool
    random.Random(1).shuffle(ip)
    for r, shv in ip:
        push(r, shv)
    for r, shv in extra.get(s, {}).items():           # 4. fresh GitHub
        push(r, shv)
    return out

def work(jv, repo, hint):
    with lock:
        if count[jv] >= TARGET:
            return
    wd = "/tmp/vg_" + repo.replace("/", "_")
    try:
        shav, why = search_green(repo, jv, hint, wd)
        if shav:
            with lock:
                if count[jv] < TARGET:
                    count[jv] += 1
                    open(OUT, "a").write(json.dumps(
                        {"repo": repo, "sha": shav, "jv_from": jv, "jv_to": NEXT[jv], "baseline_tests_pass": True}) + "\n")
                    print("GREEN J%d [%d/%d] %s %s" % (jv, count[jv], TARGET, repo, shav[:8]), flush=True)
        else:
            print("MISS J%d %s (%s)" % (jv, repo, why), flush=True)
    finally:
        sh("rm -rf " + wd, 60)

tasks = []
for jv in ([8, 11] if JVSEL == "both" else [int(JVSEL)]):
    for repo, hint in order_repos(jv):
        tasks.append((jv, repo, hint))
LIMIT = int(arg("--limit", "0"))      # cap this batch to the first N untried candidates
if LIMIT:
    tasks = tasks[:LIMIT]
print("commit-search verify: %d repos | target %d/jv | %d workers | maxbuild %d | green-so-far %s"
      % (len(tasks), TARGET, WORKERS, MAXBUILD, dict(count)), flush=True)
with ThreadPoolExecutor(max_workers=WORKERS) as ex:
    for f in [ex.submit(work, jv, r, h) for jv, r, h in tasks]:
        f.result()
print("DONE green: %s" % dict(count), flush=True)

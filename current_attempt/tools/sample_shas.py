"""attempt-12 sha-sampler: repo-list -> per-run randomized *valid* baselines.

Contract: reads dataset-repos.json (repo names only), writes dataset-shas.json (the sampled
baselines for this run; regenerated each round). For each repo, walk its commits in seeded-random
order and accept the FIRST commit that (a) declares Java 8/11/17 in its pom AND (b) compiles
under that JDK (`mvn test-compile`). Bounded by --max-attempts compile checks (default 10).

A different --seed => different random order => (usually) a different accepted sha, so the
eval is a moving target the skill/recipes must generalize to. jv_to = next LTS (8->11, 11->17,
17->21). Junk (no-pom / already>=21 / non-compiling) is rejected by the search itself.

Usage: python3 sample_shas.py --seed N [--max-attempts 10] [--scan-cap 150] [--limit M] [--repos a/b,c/d]
Output: current_attempt/dataset-shas.json = [{repo, sha, jv_from, jv_to, attempts}] (regenerated per run)
"""
import json, subprocess, sys, os, random
A = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"
NEXT_ALL = {8: 11, 11: 17, 17: 21, 21: 25}  # bumpable LTS -> next LTS

def arg(n, d=None):
    for a in sys.argv:
        if a.startswith(n + "="):
            return a.split("=", 1)[1]
    return d

SEED = int(arg("--seed", "0"))
MAX_ATTEMPTS = int(arg("--max-attempts", "10"))   # max COMPILE attempts per repo
SCAN_CAP = int(arg("--scan-cap", "150"))          # max commits inspected for eligibility (cheap)
LIMIT = arg("--limit"); REPOS_OVERRIDE = arg("--repos")
REPOS_FILE = arg("--repos-file"); OUT = arg("--out")
ONLY = arg("--only-from")  # restrict to a single jv_from (e.g. 21 for the 21->25 sweep)
NEXT = {int(ONLY): NEXT_ALL[int(ONLY)]} if ONLY else NEXT_ALL
MULTI = "--multi" in sys.argv   # find a baseline per Java version, not just the first
if REPOS_FILE:
    REPOS = [r.strip() for r in open(REPOS_FILE) if r.strip()]
elif REPOS_OVERRIDE:
    REPOS = REPOS_OVERRIDE.split(",")
else:
    REPOS = json.load(open(A + "/dataset-repos.json"))
if LIMIT:
    REPOS = REPOS[:int(LIMIT)]

def sh(c, to=300):
    try:
        return subprocess.run(c, shell=True, capture_output=True, text=True, timeout=to)
    except subprocess.TimeoutExpired:
        class R: returncode = 124; stdout = ""; stderr = ""
        return R()

def reap(wd):
    # build container writes root-owned target/ files; remove via a root container
    import os as _os
    sh("docker run --rm --user root -v /tmp:/scratch --entrypoint sh j21-fitness:latest -c 'rm -rf /scratch/" + _os.path.basename(wd) + "'", 180)


def detect_jv(wd):
    out = sh("grep -rhoE '<(maven.compiler.release|java.version|maven.compiler.target|release|source)>[0-9][0-9.]*' "
             + wd + " --include=pom.xml 2>/dev/null").stdout.split()
    vs = []
    for tok in out:
        num = tok.split(">")[-1]                         # '1.8' | '8' | '11'
        try:
            v = int(num[2:].split(".")[0]) if num.startswith("1.") and len(num) > 2 else int(num.split(".")[0])
        except ValueError:
            continue
        if v in (8, 11, 17, 21, 25):                       # 1.8 -> 8 (classic Java-8 notation)
            vs.append(v)
    return max(vs) if vs else None

def detect_jv_gradle(wd):
    import re, glob as _g
    txt = ""
    for f in (_g.glob(wd + "/build.gradle") + _g.glob(wd + "/build.gradle.kts")
              + _g.glob(wd + "/*/build.gradle") + _g.glob(wd + "/*/build.gradle.kts")):
        try: txt += open(f, errors="ignore").read() + "\n"
        except Exception: pass
    vs = []
    vs += [int(m) for m in re.findall(r"JavaLanguageVersion\.of\(\s*(\d+)\s*\)", txt)]
    vs += [8 for _ in re.findall(r"VERSION_1_8", txt)]
    vs += [int(m) for m in re.findall(r"VERSION_(\d+)\b", txt)]
    vs += [int(m) for m in re.findall(r"(?:source|target)Compatibility\s*=?\s*[\"\']?(?:1\.)?(\d{1,2})\b", txt)]
    vs += [int(m) for m in re.findall(r"languageVersion\s*=\s*[\"\']?(\d{1,2})\b", txt)]
    vs = [v for v in vs if v in (8, 11, 17, 21, 25)]
    return max(vs) if vs else None

def process_repo(repo):
    wd = "/tmp/samp_" + repo.replace("/", "_")
    reap(wd)
    mirror = "/var/cache/git-mirrors/" + repo + ".git"
    if os.path.isdir(mirror):
        sh(f"git clone -q {mirror} {wd}", 300)
    else:
        sh(f'git clone -q -c credential.helper="!gh auth git-credential" https://github.com/{repo} {wd}', 600)
    if not os.path.isdir(wd + "/.git"):
        print("CLONE-FAIL", repo, flush=True); return []
    commits = sh(f"git -C {wd} log --all --pretty=%H", 60).stdout.split()
    random.Random(f"{SEED}:{repo}").shuffle(commits)
    found = {}; compiles = 0; scanned = 0
    target_n = len(NEXT) if MULTI else 1
    for sha in commits:
        if scanned >= SCAN_CAP or compiles >= MAX_ATTEMPTS or len(found) >= target_n:
            break
        scanned += 1
        sh(f"git -C {wd} checkout -q {sha} 2>/dev/null", 60)
        is_mvn = os.path.isfile(wd + "/pom.xml")
        is_gradle = os.path.isfile(wd + "/build.gradle") or os.path.isfile(wd + "/build.gradle.kts")
        if not (is_mvn or is_gradle):
            continue
        jv = detect_jv(wd) if is_mvn else detect_jv_gradle(wd)   # prefer maven when both present
        if jv not in NEXT or jv in found:
            continue
        compiles += 1
        if is_mvn:
            rc = sh(f"export PATH=$HOME/bin:$PATH; cd {wd} && JDK={jv} mvn -q -B -ntp -DskipTests test-compile", 600).returncode
        else:
            rc = sh(f"export PATH=$HOME/bin:$PATH; cd {wd} && JDK={jv} WORK_DIR={wd} gradle -q testClasses", 900).returncode
        if rc == 0:
            found[jv] = sha
            print(f"  FOUND {repo} {sha[:8]} jv {jv}->{NEXT[jv]} ({len(found)}/{target_n}, attempt {compiles}/{MAX_ATTEMPTS})", flush=True)
        else:
            print(f"  noncompile {repo} {sha[:8]} jv {jv} (attempt {compiles}/{MAX_ATTEMPTS})", flush=True)
    reap(wd)
    if found:
        return [{"repo": repo, "sha": sha, "jv_from": jv, "attempts": compiles} for jv, sha in sorted(found.items())]
    print(f"  NO-VALID-BASELINE {repo} (scanned {scanned}, {compiles} compile attempts)", flush=True)
    return []

WORKERS = int(arg("--workers", "1"))
ds = OUT if OUT else A + "/dataset-shas.json"
out = []
if WORKERS > 1:
    import threading
    from concurrent.futures import ThreadPoolExecutor
    _lock = threading.Lock()
    _jl = open(ds + ".jsonl", "a")            # incremental + crash-safe; workers pull next repo from the pool queue
    def _run(repo):
        res = process_repo(repo)
        with _lock:
            for e in res:
                _jl.write(json.dumps(e) + "\n"); _jl.flush()
            out.extend(res)
    with ThreadPoolExecutor(max_workers=WORKERS) as _ex:
        list(_ex.map(_run, REPOS))
    _jl.close()
else:
    for repo in REPOS:
        out.extend(process_repo(repo))
json.dump(out, open(ds, "w"), indent=1)
print(f"\nSEED={SEED} max_attempts={MAX_ATTEMPTS}: {len(out)}/{len(REPOS)} repos got a valid compiling "
      f"8/11/17 baseline -> dataset-shas.json (seed {SEED})", flush=True)

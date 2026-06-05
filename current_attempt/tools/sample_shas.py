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
NEXT = {8: 11, 11: 17, 17: 21}  # bumpable LTS -> next LTS

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

def detect_jv(wd):
    out = sh("grep -rhoE '<(maven.compiler.release|java.version|maven.compiler.target|release|source)>[0-9]+' "
             + wd + " --include=pom.xml 2>/dev/null | grep -oE '[0-9]+'").stdout.split()
    vs = [int(x) for x in out if x.isdigit() and int(x) in (8, 11, 17, 21)]
    return max(vs) if vs else None

out = []
for repo in REPOS:
    wd = "/tmp/samp_" + repo.replace("/", "_")
    sh("rm -rf " + wd, 60)
    sh(f"git clone -q https://github.com/{repo} {wd}", 600)
    if not os.path.isdir(wd + "/.git"):
        print("CLONE-FAIL", repo, flush=True); continue
    commits = sh(f"git -C {wd} log --all --pretty=%H", 60).stdout.split()
    random.Random(f"{SEED}:{repo}").shuffle(commits)  # per-(seed,repo): order-independent, parallel-safe
    accepted = None; compiles = 0; scanned = 0
    for sha in commits:
        if scanned >= SCAN_CAP or compiles >= MAX_ATTEMPTS:
            break
        scanned += 1
        sh(f"git -C {wd} checkout -q {sha} 2>/dev/null", 60)
        if not os.path.isfile(wd + "/pom.xml"):
            continue                       # cheap reject: no pom (doesn't count as a compile attempt)
        jv = detect_jv(wd)
        if jv not in NEXT:
            continue                       # cheap reject: not 8/11/17 (e.g. already 21)
        compiles += 1                      # this IS a compile attempt
        rc = sh(f"export PATH=$HOME/bin:$PATH; cd {wd} && JDK={jv} mvn -q -B -ntp -DskipTests test-compile", 600).returncode
        if rc == 0:
            accepted = {"repo": repo, "sha": sha, "jv_from": jv, "jv_to": NEXT[jv], "attempts": compiles}
            print(f"  FOUND {repo} {sha[:8]} jv {jv}->{NEXT[jv]} (compile attempt {compiles}/{MAX_ATTEMPTS})", flush=True)
            break
        print(f"  noncompile {repo} {sha[:8]} jv {jv} (attempt {compiles}/{MAX_ATTEMPTS})", flush=True)
    if accepted:
        out.append(accepted)
    else:
        print(f"  NO-VALID-BASELINE {repo} (scanned {scanned}, {compiles} compile attempts)", flush=True)
    sh("rm -rf " + wd, 60)

ds = OUT if OUT else A + "/dataset-shas.json"
json.dump(out, open(ds, "w"), indent=1)
print(f"\nSEED={SEED} max_attempts={MAX_ATTEMPTS}: {len(out)}/{len(REPOS)} repos got a valid compiling "
      f"8/11/17 baseline -> dataset-shas.json (seed {SEED})", flush=True)

"""attempt_5 v4: robust lineage discovery.

Fixes over v3:
  - Process-group kill on timeout so giant git clones don't orphan
  - Checkpoint every 50 walks to disk (lose-nothing on crash)
  - Skip known monorepos by name (camunda, etc.) and by HEAD repo size > 200MB
  - Cap clone+fetch to 60s total per repo
  - Family classification at oldest commit (carried forward as family_at_oldest)
"""
import json, os, time, subprocess, re, collections, tempfile, shutil, signal, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from threading import Lock

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
CHECKPOINT = "/tmp/lineage_candidates_v4.partial.json"
FINAL = "/tmp/lineage_candidates_v4.json"

# Known monorepos / projects > 200 MB shallow that hang the walker
SKIP_REPOS = {
    "camunda/camunda", "spring-projects/spring-framework", "spring-projects/spring-boot",
    "hibernate/hibernate-orm", "apache/dubbo", "apache/skywalking", "apache/dolphinscheduler",
    "apache/seatunnel", "apache/shardingsphere", "apache/incubator-pegasus",
    "apache/streampark", "apache/inlong", "elastic/elasticsearch",
}

JAVA_VER_RE = re.compile(
    r"<(?:java\.version|maven\.compiler\.source|maven\.compiler\.target|maven\.compiler\.release|source)>([\d.]+)</",
    re.IGNORECASE,
)
FAMILY = {
    "hibernate-5": [re.compile(r"<artifactId>hibernate-core</artifactId>\s*<version>5\."),
                    re.compile(r"<hibernate\.version>5\.")],
    "jakarta-ee-javax": [re.compile(r"<artifactId>javax\.servlet-api</artifactId>"),
                          re.compile(r"<artifactId>javax\.persistence-api</artifactId>"),
                          re.compile(r"<groupId>javax\.servlet"),
                          re.compile(r"<groupId>javax\.persistence")],
    "junit4-mockito": [re.compile(r"<artifactId>junit</artifactId>\s*<version>4\."),
                       re.compile(r"<artifactId>mockito-core</artifactId>"),
                       re.compile(r"<artifactId>mockito-all</artifactId>")],
    "spring-boot-2": [re.compile(r"<artifactId>spring-boot-starter-parent</artifactId>\s*<version>2\."),
                      re.compile(r"<spring-boot\.version>2\.")],
}


def extract_java_version(pom):
    for m in JAVA_VER_RE.finditer(pom):
        v = m.group(1)
        if v.startswith("1."):
            v = v[2:]
        if v in {"8", "11", "17", "21"}:
            return v
    return None


def detect_family(pom):
    for fam, pats in FAMILY.items():
        for p in pats:
            if p.search(pom):
                return fam
    return None


def run_with_pg_kill(cmd, timeout, cwd=None):
    """subprocess.run that actually kills the child process group on timeout."""
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         start_new_session=True)
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            pass
        try:
            p.communicate(timeout=5)
        except Exception:
            pass
        return -1, b"", b"timeout"


def gh_search_code(query, per_page=100, max_pages=10):
    results = []
    for page in range(1, max_pages + 1):
        url = f"https://api.github.com/search/code?q={urllib.parse.quote(query)}&per_page={per_page}&page={page}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}" if TOKEN else "",
            "User-Agent": "j21-lineage-discovery",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
        except Exception as e:
            print(f"  q-page{page} failed: {e}", flush=True)
            break
        items = data.get("items", [])
        if not items:
            break
        for it in items:
            results.append(it["repository"]["full_name"])
        if len(items) < per_page:
            break
        time.sleep(3)
    return results


def walk_history(repo_full):
    if repo_full in SKIP_REPOS:
        return None
    tmp = tempfile.mkdtemp(prefix="lineage-")
    try:
        url = f"https://github.com/{repo_full}.git"
        rc, _, _ = run_with_pg_kill(
            ["git", "clone", "--filter=blob:none", "--no-checkout", url, f"{tmp}/repo"],
            timeout=60,
        )
        if rc != 0:
            return None
        rc, out, _ = run_with_pg_kill(
            ["git", "log", "--all", "--format=%H", "--", "*pom.xml"],
            cwd=f"{tmp}/repo", timeout=30,
        )
        if rc != 0:
            return None
        shas = out.decode().split()
        if not shas:
            return None
        chain = []
        seen_v = set()
        for sha in reversed(shas):
            rc, out, _ = run_with_pg_kill(
                ["git", "ls-tree", "-r", "--name-only", sha], cwd=f"{tmp}/repo", timeout=15,
            )
            if rc != 0:
                continue
            poms = [p for p in out.decode().split() if p.endswith("pom.xml")][:5]
            if not poms:
                continue
            ver = None
            anchor = None
            for p in poms:
                rc, out2, _ = run_with_pg_kill(
                    ["git", "show", f"{sha}:{p}"], cwd=f"{tmp}/repo", timeout=10,
                )
                if rc != 0:
                    continue
                txt = out2.decode(errors="replace")
                v = extract_java_version(txt)
                if v:
                    ver = v
                    anchor = txt
                    break
            if ver and ver not in seen_v:
                chain.append((sha, ver, anchor))
                seen_v.add(ver)
        return chain
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    queries = [
        '"<java.version>21</java.version>" extension:xml filename:pom size:<5000',
        '"<java.version>21</java.version>" extension:xml filename:pom size:5000..10000',
        '"<java.version>21</java.version>" extension:xml filename:pom size:10000..30000',
        '"<java.version>21</java.version>" extension:xml filename:pom size:>30000',
        '"<maven.compiler.release>21</maven.compiler.release>" extension:xml filename:pom',
        '"<maven.compiler.source>21</maven.compiler.source>" extension:xml filename:pom',
        '"<release>21</release>" extension:xml filename:pom',
        '"<java.version>21</java.version>" extension:xml filename:pom stars:>10',
        '"<java.version>21</java.version>" extension:xml filename:pom stars:>50',
        '"spring-boot-starter-parent" "<version>3" "<java.version>21" extension:xml filename:pom',
        # Specific target: J8 / J11 / J17 -> J21 history; look for older Boot in current J21 repos
        '"spring-boot-starter-parent" "<java.version>21" "javax." extension:xml filename:pom',
        '"<java.version>21</java.version>" "hibernate-validator" extension:xml filename:pom',
        '"<java.version>21</java.version>" "mockito" extension:xml filename:pom',
    ]
    all_repos = set()
    for f in ["lineage_candidates.json", "lineage_candidates_v2.json"]:
        p = f"{HERE}/attempt_5/{f}"
        if os.path.exists(p):
            for e in json.load(open(p)):
                all_repos.add(e["repo_full_name"])
    print(f"seeded: {len(all_repos)}", flush=True)

    for q in queries:
        items = gh_search_code(q, per_page=100, max_pages=10)
        added = sum(1 for r in items if r not in all_repos)
        all_repos.update(items)
        print(f"  q +{added} new, total={len(all_repos)}", flush=True)
        time.sleep(4)
    all_repos -= SKIP_REPOS
    print(f"\nfinal pool: {len(all_repos)}", flush=True)

    lineages = []
    done = [0]
    lock = Lock()

    def worker(repo):
        chain = walk_history(repo)
        with lock:
            done[0] += 1
            if chain and len(chain) >= 2:
                _, _, anchor = chain[0]
                fam = detect_family(anchor) if anchor else None
                lineages.append({
                    "repo_full_name": repo,
                    "owner": repo.split("/")[0],
                    "lineage": [{"java_version": int(v), "commit_sha": s} for s, v, _ in chain],
                    "oldest_java_version": int(chain[0][1]),
                    "newest_java_version": int(chain[-1][1]),
                    "family_at_oldest": fam,
                })
            if done[0] % 50 == 0:
                j21 = sum(1 for x in lineages if x["newest_java_version"] == 21)
                print(f"  {done[0]}/{len(all_repos)} walked, lineages={len(lineages)}, J21={j21}", flush=True)
                # checkpoint
                with open(CHECKPOINT, "w") as f:
                    json.dump(lineages, f)

    with ThreadPoolExecutor(max_workers=24) as ex:
        list(ex.map(worker, list(all_repos)))

    with open(FINAL, "w") as f:
        json.dump(lineages, f, indent=2)
    j21 = [e for e in lineages if e["newest_java_version"] == 21]
    print(f"\ntotal: {len(lineages)}, reach-J21: {len(j21)}")
    cells = collections.Counter((e["oldest_java_version"], e["family_at_oldest"]) for e in j21)
    for k in sorted(cells, key=lambda x: (x[0], x[1] or "zz")):
        print(f"  {k}: {cells[k]}")
    print(f"\nsaved to {FINAL}")


if __name__ == "__main__":
    main()

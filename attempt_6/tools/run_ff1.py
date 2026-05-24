"""ff #1 minimal runner (attempt_6 v0): per single-step stage, apply
UpgradeToJava<jv_to> + measure build outcome. Honours ff #2 contract — multi-step
stages are excluded from the recipe corpus.

Output: attempt_6/ff1_results.json — list of {repo, sha_from, jv_from, jv_to,
build_pre, recipe_applied, build_post, error}.
"""
import json, os, subprocess, tempfile, shutil, time, sys, threading
from concurrent.futures import ThreadPoolExecutor

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
CORPUS = f"{HERE}/attempt_5/lineage_dataset_v4_final.json"
GIT_MIRRORS = "/var/cache/git-mirrors"
WORK_ROOT = "/tmp/ff1_work"
IMAGE = "j21-fitness:latest"
OUT = f"{HERE}/attempt_6/ff1_results.json"
RUN_ONE_STAGE = f"{HERE}/attempt_6/tools/run_one_stage_v2.sh"

RECIPE_NAME_FOR = {11: "org.openrewrite.java.migrate.Java8toJava11",   # NOT UpgradeToJava11 — different naming
                   17: "org.openrewrite.java.migrate.UpgradeToJava17",
                   21: "org.openrewrite.java.migrate.UpgradeToJava21"}


def adjacent(jf, jt):
    return (jf, jt) in [(8, 11), (11, 17), (17, 21)]


def ensure_mirror(repo):
    owner, name = repo.split("/", 1)
    mirror = f"{GIT_MIRRORS}/{owner}/{name}.git"
    if os.path.exists(mirror):
        return mirror
    url = f"https://github.com/{repo}.git"
    os.makedirs(os.path.dirname(mirror), exist_ok=True)
    try:
        subprocess.run(["git", "clone", "--mirror", url, mirror],
                       capture_output=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None
    return mirror if os.path.exists(mirror) else None


def checkout_into(repo, sha, dst):
    """Materialise a working tree at sha into dst. Fetches from github directly because
    /var/cache/git-mirrors is blob:none (fine for diff/log, no good for checkout)."""
    os.makedirs(dst, exist_ok=True)
    url = f"https://github.com/{repo}.git"
    try:
        subprocess.run(["git", "init", "-q"], cwd=dst, capture_output=True, timeout=30)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=dst, capture_output=True, timeout=30)
        r = subprocess.run(["git", "fetch", "--depth", "1", "origin", sha],
                           cwd=dst, capture_output=True, timeout=600)
        if r.returncode != 0:
            r = subprocess.run(["git", "fetch", "origin", sha], cwd=dst, capture_output=True, timeout=900)
            if r.returncode != 0: return False
        r = subprocess.run(["git", "checkout", "-q", sha], cwd=dst, capture_output=True, timeout=60)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        return False


def detect_build_tool(work):
    if os.path.exists(f"{work}/pom.xml"): return "maven"
    if any(os.path.exists(f"{work}/{x}") for x in ("build.gradle", "build.gradle.kts", "settings.gradle", "settings.gradle.kts")):
        return "gradle"
    # search subdirs
    for root, dirs, files in os.walk(work):
        if "pom.xml" in files: return "maven"
        if "build.gradle" in files or "build.gradle.kts" in files: return "gradle"
        if root.count("/") - work.count("/") > 3: break
    return None


def write_recipe_yml(path, recipe_class):
    yml = f"""---
type: specs.openrewrite.org/v1beta/recipe
name: org.example.attempt6.UpgradeJava
recipeList:
  - {recipe_class}
"""
    open(path, "w").write(yml)


def run_phase(work_dir, recipes_dir, out_log, phase, jdk, build_tool, stage_recipe=None):
    """Invoke run_one_stage.sh inside j21-fitness container with the given PHASE."""
    env = {
        "STAGE_JDK": str(jdk),
        "BUILD_TOOL": build_tool,
        "STAGE_LOG": f"/out/{os.path.basename(out_log)}",
        "PHASE": phase,
    }
    if stage_recipe is not None:
        env["STAGE_RECIPE"] = f"/recipes/{os.path.basename(stage_recipe)}"

    env_args = []
    for k, v in env.items():
        env_args += ["-e", f"{k}={v}"]

    out_dir = os.path.dirname(out_log)
    cmd = ["docker", "run", "--rm",
           "-v", f"{work_dir}:/work/src",
           "-v", f"{recipes_dir}:/recipes:ro",
           "-v", f"{out_dir}:/out",
           "--network", "host",
           "-v", f"{HERE}/attempt_6/tools/run_one_stage_v2.sh:/entry.sh:ro",
           *env_args,
           "--entrypoint", "bash", IMAGE, "/entry.sh"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=1800)
        return r.returncode
    except subprocess.TimeoutExpired:
        return 124


def process_stage(stage, idx, total):
    repo, sha_from, jf, jt = stage["repo"], stage["sha_from"], stage["jv_from"], stage["jv_to"]
    label = f"{repo} J{jf}->J{jt}"
    result = {"repo": repo, "sha_from": sha_from, "jv_from": jf, "jv_to": jt,
              "build_pre": None, "recipe_applied": None, "build_post": None,
              "error": None, "build_tool": None}

    work_dir = tempfile.mkdtemp(prefix="ff1_", dir=WORK_ROOT)
    recipes_dir = tempfile.mkdtemp(prefix="ff1rec_", dir=WORK_ROOT)
    out_dir = tempfile.mkdtemp(prefix="ff1out_", dir=WORK_ROOT)
    try:
        if not checkout_into(repo, sha_from, work_dir):
            result["error"] = "checkout_failed"
            return result

        build_tool = detect_build_tool(work_dir)
        result["build_tool"] = build_tool
        if build_tool != "maven":
            result["error"] = f"unsupported_build_tool:{build_tool}"
            print(f"  [{idx}/{total}] {label}: skip {build_tool}", flush=True)
            return result

        log = os.path.join(out_dir, f"stage.log")

        # 1) build_pre under SOURCE JDK (jv_from)
        rc = run_phase(work_dir, recipes_dir, log, "build_pre", jf, build_tool)
        result["build_pre"] = (rc == 0)

        # 2) recipe under TARGET JDK (jv_to)
        recipe_path = os.path.join(recipes_dir, "stage.yml")
        write_recipe_yml(recipe_path, RECIPE_NAME_FOR[jt])
        rc = run_phase(work_dir, recipes_dir, log, "recipe", jt, build_tool,
                       stage_recipe=recipe_path)
        result["recipe_applied"] = (rc == 0)

        # 3) build_post under TARGET JDK (jv_to)
        rc = run_phase(work_dir, recipes_dir, log, "build_post", jt, build_tool)
        result["build_post"] = (rc == 0)

        # keep tail of log for debugging
        try:
            with open(log) as f:
                lines = f.readlines()
            result["log_tail"] = "".join(lines[-25:])
        except Exception:
            pass

        print(f"  [{idx}/{total}] {label}: pre={result['build_pre']} recipe={result['recipe_applied']} post={result['build_post']}",
              flush=True)
        return result
    finally:
        for d in (work_dir, recipes_dir, out_dir):
            shutil.rmtree(d, ignore_errors=True)


def main():
    os.makedirs(WORK_ROOT, exist_ok=True)
    corpus = json.load(open(CORPUS))
    stages = []
    for e in corpus:
        vl = sorted(e["verified_lineage"], key=lambda s: s["java_version"])
        for i in range(len(vl) - 1):
            jf, jt = vl[i]["java_version"], vl[i + 1]["java_version"]
            if not adjacent(jf, jt): continue
            stages.append({
                "repo": e["repo_full_name"],
                "sha_from": vl[i]["commit_sha"],
                "sha_to": vl[i + 1]["commit_sha"],
                "jv_from": jf, "jv_to": jt,
            })

    # CLI filter: --limit N (just first N stages), --repos REPO1,REPO2
    limit = None
    only_repos = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--limit" and i + 1 < len(args): limit = int(args[i + 1])
        if a == "--repos" and i + 1 < len(args): only_repos = set(args[i + 1].split(","))
    if only_repos:
        stages = [s for s in stages if s["repo"] in only_repos]
    if limit:
        stages = stages[:limit]

    # Resume: skip stages whose result is already recorded AND succeeded recipe step
    # (or where the result was a non-recoverable error). Re-run J8->J11 stages because
    # they were run with the wrong recipe name.
    existing = []
    if os.path.exists(OUT):
        try: existing = json.load(open(OUT))
        except: existing = []
    done_keys = set()
    for x in existing:
        # Only treat as "done" if recipe_applied is True (J8->J11 with old buggy name had recipe_applied=False)
        if x.get("recipe_applied") is True:
            done_keys.add((x["repo"], x["sha_from"]))
    if done_keys:
        before = len(stages)
        stages = [s for s in stages if (s["repo"], s["sha_from"]) not in done_keys]
        print(f"resume: {before - len(stages)} stages already done", flush=True)
    # Preserve old results, append new ones
    results_existing = [x for x in existing if (x["repo"], x["sha_from"]) in done_keys]

    print(f"total adjacent stages: {len(stages)}", flush=True)

    results = list(results_existing)
    lock = threading.Lock()

    def go(i_s):
        i, s = i_s
        r = process_stage(s, i + 1, len(stages))
        with lock:
            results.append(r)
            json.dump(results, open(OUT, "w"), indent=2)
        return r

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(go, enumerate(stages)))

    pre_ok = sum(1 for r in results if r.get("build_pre"))
    post_ok = sum(1 for r in results if r.get("build_post"))
    print(f"\n=== summary ===")
    print(f"  total:           {len(results)}")
    print(f"  build_pre  pass: {pre_ok}")
    print(f"  build_post pass: {post_ok}")


if __name__ == "__main__":
    main()

"""ff #4 runner: per stage, apply recipe (default UpgradeToJava<jv_to>) + capture
per-file diff + extract recipe-side intents via the canonical extractor. Emits
recipe_samples/<slug>/{intents.json, breaking.json, polishment.json, <rel>.diff,
commit_log.txt} in same schema as item 3.

Per ff #1 contract, reads attempt_6/recipe.yaml if present, else defaults to
{UpgradeToJava<jv_to>} per stage (first-iteration baseline).
"""
import json, os, subprocess, tempfile, shutil, time, sys, threading, importlib.util
from concurrent.futures import ThreadPoolExecutor

# Reuse item 3's canonical Qwen extractor (ask_qwen + canonical_atom + SYSTEM prompt)
_rf4_spec = importlib.util.spec_from_file_location('rf3', '/tmp/run_fitness4.py')
rf3 = importlib.util.module_from_spec(_rf4_spec); _rf4_spec.loader.exec_module(rf3)

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
CORPUS = f"{HERE}/attempt_5/lineage_dataset_v4_final.json"
GIT_MIRRORS = "/var/cache/git-mirrors"
WORK_ROOT = "/tmp/ff1_work"
IMAGE = "j21-fitness:latest"
OUT = f"{HERE}/attempt_6/ff4_results.json"
RUN_ONE_STAGE = f"{HERE}/attempt_6/tools/run_one_stage_v2.sh"
RECIPE_SAMPLES = f"{HERE}/attempt_6/recipe_samples"

import yaml as _yaml
RECIPE_YAML = f"{HERE}/attempt_6/recipe.yaml"
def _load_recipe_yaml():
    try:
        with open(RECIPE_YAML) as f:
            data = _yaml.safe_load(f) or {}
        # Keys may be int or str; normalise to int
        return {int(k): list(v or []) for k, v in data.items()}
    except FileNotFoundError:
        raise SystemExit(f"recipe.yaml not found at {RECIPE_YAML}; item 1 must emit it first.")
RECIPE_COMPOSITION = _load_recipe_yaml()
# Back-compat for log lines that referenced a single name
def _recipe_label(jv_to):
    return "+".join(RECIPE_COMPOSITION.get(jv_to, []) or [f"NO_RECIPE_FOR_J{jv_to}"])
RECIPE_NAME_FOR = {jv: _recipe_label(jv) for jv in RECIPE_COMPOSITION}


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


def write_recipe_yml(path, jv_to):
    """Emit an OpenRewrite YAML recipe composing all recipes from RECIPE_COMPOSITION[jv_to]."""
    names = RECIPE_COMPOSITION.get(jv_to, [])
    body = "---\ntype: specs.openrewrite.org/v1beta/recipe\nname: org.example.attempt6.UpgradeJava\nrecipeList:\n"
    for n in names:
        body += f"  - {n}\n"
    open(path, "w").write(body)


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
           "--network", "mvn-cache",
           "-v", "/home/vmihaylov/.m2-fitness:/root/.m2",
           "-v", "/home/vmihaylov/maven-config/settings.xml:/root/.m2/settings.xml:ro",
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

        # 1b) test_pre under SOURCE JDK (jv_from), only if build_pre passed
        if result.get("build_pre"):
            rc_t = run_phase(work_dir, recipes_dir, log, "test_pre", jf, build_tool)
            result["tests_pre"] = (rc_t == 0)
        else:
            result["tests_pre"] = None

        # 2) recipe under TARGET JDK (jv_to)
        recipe_path = os.path.join(recipes_dir, "stage.yml")
        write_recipe_yml(recipe_path, jt)
        rc = run_phase(work_dir, recipes_dir, log, "recipe", jt, build_tool,
                       stage_recipe=recipe_path)
        result["recipe_applied"] = (rc == 0)

        # 3) build_post under TARGET JDK (jv_to)
        rc = run_phase(work_dir, recipes_dir, log, "build_post", jt, build_tool)
        result["build_post"] = (rc == 0)

        # 4) test_post under TARGET JDK if build_post passed
        if result.get("build_post"):
            rc_t = run_phase(work_dir, recipes_dir, log, "test_post", jt, build_tool)
            result["tests_post"] = (rc_t == 0)
        else:
            result["tests_post"] = None

        # 5) capture recipe diff per modified file, run canonical intent extractor,
        #    emit recipe_samples/<slug>/ in item 3 schema.
        if result.get("recipe_applied"):
            try:
                _capture_recipe_samples(repo, sha_from, jf, jt, work_dir)
            except Exception as _e:
                result["extract_error"] = str(_e)[:200]

        # keep tail of log for debugging, also append FULL log to /tmp/ff1_stages.log
        # so Vector (which tails /tmp/*.log) can feed it to the compactor.
        try:
            with open(log) as f:
                lines = f.readlines()
            result["log_tail"] = "".join(lines[-25:])
            header = "\n=== " + label + " sha=" + sha_from[:8] + " ===\n"
            with open("/tmp/ff1_stages.log", "a") as out:
                out.write(header)
                out.writelines(lines)
        except Exception as _e:
            pass

        print(f"  [{idx}/{total}] {label}: pre={result['build_pre']} recipe={result['recipe_applied']} post={result['build_post']}",
              flush=True)
        return result
    finally:
        for d in (work_dir, recipes_dir, out_dir):
            shutil.rmtree(d, ignore_errors=True)




def _capture_recipe_samples(repo, sha_from, jv_from, jv_to, work_dir):
    """git diff against sha_from in work_dir; for each modified file run rf3.ask_qwen;
    write recipe_samples/<slug>/ in item 3 schema (intents.json, breaking.json, polishment.json,
    <rel>.diff, commit_log.txt)."""
    slug = repo.replace("/", "_") + f"__J{jv_from}toJ{jv_to}"
    dst = f"{RECIPE_SAMPLES}/{slug}"
    os.makedirs(dst, exist_ok=True)

    # git diff --name-only (work_dir is git-init'd via checkout_into)
    r = subprocess.run(["git", "diff", "--name-only"], cwd=work_dir, capture_output=True, timeout=60)
    files = [f for f in r.stdout.decode(errors="replace").splitlines() if f.strip()]
    diffs = {}
    for rel in [f for f in files[:200] if not any(d in ("/"+f) for d in ("/target/", "/build/", "/.gradle/")) and not f.endswith((".class", ".lst"))][:50]:  # cap defensively
        rr = subprocess.run(["git", "diff", "--", rel], cwd=work_dir, capture_output=True, timeout=60)
        text = rr.stdout.decode(errors="replace")
        if text.strip():
            diffs[rel] = text

    meta = {"repo": repo, "stage": f"J{jv_from}->J{jv_to}",
            "sha_from": sha_from, "recipe": RECIPE_NAME_FOR.get(jv_to, "")}

    if not diffs:
        for name in ("intents.json", "breaking.json", "polishment.json"):
            json.dump({"meta": meta, "by_file": {}}, open(f"{dst}/{name}", "w"), indent=2)
        open(f"{dst}/commit_log.txt", "w").write(f"recipe: {meta['recipe']}\n")
        return

    open(f"{dst}/commit_log.txt", "w").write(f"recipe: {meta['recipe']}\n")
    for rel, dt in diffs.items():
        open(f"{dst}/{rel.replace('/', '__')}.diff", "w").write(dt)

    # Apply ff #3's prefilter and extractor
    by_file = {}
    for rel, dt in diffs.items():
        intents = rf3.ask_qwen(rel, jv_from, jv_to, dt, f"recipe: {meta['recipe']}") or []
        by_file[rel] = [rf3.canonical_atom(a) for a in intents]

    json.dump({"meta": meta, "by_file": by_file}, open(f"{dst}/intents.json", "w"), indent=2)
    breaking = {rel: [it for it in xs if it.get("bucket") == "breaking"] for rel, xs in by_file.items()}
    polishment = {rel: [it for it in xs if it.get("bucket") != "breaking"] for rel, xs in by_file.items()}
    json.dump({"meta": meta, "by_file": {k: v for k, v in breaking.items() if v}},
              open(f"{dst}/breaking.json", "w"), indent=2)
    json.dump({"meta": meta, "by_file": {k: v for k, v in polishment.items() if v}},
              open(f"{dst}/polishment.json", "w"), indent=2)


def main():
    os.makedirs(WORK_ROOT, exist_ok=True)
    os.makedirs(RECIPE_SAMPLES, exist_ok=True)
    corpus = json.load(open(CORPUS))
    stages = []
    for e in corpus:
        vl = sorted(e["verified_lineage"], key=lambda s: s["java_version"])
        for i in range(len(vl) - 1):
            jf, jt = vl[i]["java_version"], vl[i + 1]["java_version"]
            # adjacent-only restriction lifted; UpgradeToJava<jv_to> handles multi-step transitively
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

    print(f"total stages: {len(stages)}", flush=True)

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

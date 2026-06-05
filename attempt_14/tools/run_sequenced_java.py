"""Fully-sequenced JAVA trajectory runner.

For each stage (jv_from=8, jv_to=21):
  1. Java8toJava11                        → build under J11
  2. UpgradePluginsForJava17              → build under J17 (pom-only step)
  3. UpgradeBuildToJava17                 → build under J17
  4. java17_transforms (fused yaml)       → build under J17
  5. UpgradePluginsForJava21              → build under J21 (pom-only)
  6. UpgradeBuildToJava21                 → build under J21
  7. java21_transforms (fused yaml)       → build under J21

Each step: write tiny recipe.yaml with one or a few primitives, apply via OpenRewrite,
mvn compile under the listed JDK, record outcome.

Output per stage: trajectory JSON with per-step status.
Aggregate: compare PASS rate to iter-0 (UpgradeToJava21 one-shot).
"""
import json, os, subprocess, tempfile, shutil, time, uuid, threading, sys
from concurrent.futures import ThreadPoolExecutor

BASE = "/home/vmihaylov/java_8_11_17_to_java_21"
ATTEMPT7 = f"{BASE}/attempt_7"
IMAGE = "j21-fitness:latest"
ENTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_one_stage_v2.sh")  # sibling entry script (attempt-owned)
MAVEN_SETTINGS = "/home/vmihaylov/maven-config/settings.xml"
M2_CACHE = "/home/vmihaylov/.m2-fitness"
NET = "mvn-cache"
WORK = "/tmp/java_8_11_17_to_java_21/ff_seqjava"
OUT_DIR = f"{ATTEMPT7}/sequenced_java"
os.makedirs(WORK, exist_ok=True); os.makedirs(OUT_DIR, exist_ok=True)


# Granular Java recipe sequence for J{8,11} → J21 (no SB).
# plan() dispatches by jv_from.
def plan_for(jv_from, jv_to):
    assert jv_to == 21, "current plan supports jv_to=21 only"
    steps = [("lombok_safe_bump", jv_from, [{"name": "org.openrewrite.maven.UpgradeDependencyVersion", "groupId": "org.projectlombok", "artifactId": "lombok", "newVersion": "1.18.30"}, {"name": "org.openrewrite.maven.ChangePropertyValue", "key": "lombok.version", "newValue": "1.18.30"}, {"name": "org.openrewrite.maven.ChangePropertyValue", "key": "org.projectlombok.lombok.version", "newValue": "1.18.30"}, {"name": "org.openrewrite.maven.ChangePropertyValue", "key": "lombok-version", "newValue": "1.18.30"}, {"name": "org.openrewrite.maven.ChangePropertyValue", "key": "lombokVersion", "newValue": "1.18.30"}, {"name": "org.openrewrite.maven.ChangePropertyValue", "key": "version.lombok", "newValue": "1.18.30"}])]
    if jv_from == 8:
        steps.append(("java8_to_java11", 11, ["org.openrewrite.java.migrate.Java8toJava11"]))
    if jv_from <= 11:
        steps += _plan_to_j17_starting_under_jdk(11 if jv_from <= 11 else jv_from)
    steps += _plan_j17_to_j21()
    return steps


def _plan_to_j17_starting_under_jdk(jdk_before_bump):
    return [
        ("upgrade_plugins_for_java17",     jdk_before_bump, ["org.openrewrite.java.migrate.UpgradePluginsForJava17"]),
        ("upgrade_build_to_java17",        17, ["org.openrewrite.java.migrate.UpgradeBuildToJava17"]),
        ("java17_transforms",              17, [
            "org.openrewrite.staticanalysis.InstanceOfPatternMatch",
            "org.openrewrite.staticanalysis.AddSerialAnnotationToSerialVersionUID",
            "org.openrewrite.java.migrate.RemovedRuntimeTraceMethods",
            "org.openrewrite.java.migrate.RemovedToolProviderConstructor",
            "org.openrewrite.java.migrate.RemovedModifierAndConstantBootstrapsConstructors",
            "org.openrewrite.java.migrate.lang.ExplicitRecordImport",
            "org.openrewrite.java.migrate.DeprecatedJavaxSecurityCert",
            "org.openrewrite.java.migrate.DeprecatedLogRecordThreadID",
            "org.openrewrite.java.migrate.RemovedLegacySunJSSEProviderName",
            "org.openrewrite.java.migrate.Jre17AgentMainPreMainPublic",
            "org.openrewrite.java.migrate.DeprecatedCountStackFramesMethod",
            "org.openrewrite.java.migrate.RemovedZipFinalizeMethods",
            "org.openrewrite.java.migrate.RemovedSSLSessionGetPeerCertificateChainMethodImpl",
            "org.openrewrite.java.migrate.SunNetSslPackageUnavailable",
            "org.openrewrite.java.migrate.RemovedRMIConnectorServerCredentialTypesConstant",
            "org.openrewrite.java.migrate.RemovedFileIOFinalizeMethods",
        ]),
    ]


def _plan_j17_to_j21():
    return [
        ("upgrade_plugins_for_java21",     17, ["org.openrewrite.java.migrate.UpgradePluginsForJava21"]),
        ("upgrade_build_to_java21",        21, ["org.openrewrite.java.migrate.UpgradeBuildToJava21"]),
        ("java21_transforms",              21, [
            "org.openrewrite.java.migrate.RemoveIllegalSemicolons",
            "org.openrewrite.java.migrate.lang.ThreadStopUnsupported",
            "org.openrewrite.java.migrate.net.URLConstructorToURICreate",
            "org.openrewrite.java.migrate.util.SequencedCollection",
            "org.openrewrite.java.migrate.util.UseLocaleOf",
            "org.openrewrite.staticanalysis.ReplaceDeprecatedRuntimeExecMethods",
            "org.openrewrite.java.migrate.DeleteDeprecatedFinalize",
            "org.openrewrite.java.migrate.RemovedSubjectMethods",
        ]),
    ]


def write_recipe_yaml(path, name, recipes):
    import yaml as _yaml
    doc = {
        "type": "specs.openrewrite.org/v1beta/recipe",
        "name": name,
        "recipeList": [],
    }
    for r in recipes:
        if isinstance(r, str):
            doc["recipeList"].append(r)
        elif isinstance(r, dict):
            rname = r["name"]
            params = {k: v for k, v in r.items() if k != "name"}
            doc["recipeList"].append({rname: params} if params else rname)
        else:
            raise ValueError(f"bad recipe entry: {r!r}")
    with open(path, "w") as f:
        f.write("---\n")
        _yaml.safe_dump(doc, f, default_flow_style=False, width=10000, sort_keys=False)


def shallow_fetch(repo, sha, dst):
    try:
        url = f"https://github.com/{repo}.git"
        subprocess.run(["git", "init", "-q"], cwd=dst, capture_output=True, timeout=30)
        subprocess.run(["git", "remote", "add", "origin", url], cwd=dst, capture_output=True, timeout=10)
        r = subprocess.run(["git", "fetch", "--depth=1", "origin", sha], cwd=dst, capture_output=True, timeout=600)
        if r.returncode != 0:
            r = subprocess.run(["git", "fetch", "origin", sha], cwd=dst, capture_output=True, timeout=900)
            if r.returncode != 0: return False
        r = subprocess.run(["git", "checkout", "-q", sha], cwd=dst, capture_output=True, timeout=60)
        return r.returncode == 0
    except Exception: return False


def docker_phase(work_dir, recipes_dir, log_dir, phase, jdk, recipe_file=None, timeout=600):
    log_name = f"{phase}.log"
    env = {"STAGE_JDK": str(jdk), "BUILD_TOOL": "maven",
           "STAGE_LOG": f"/out/{log_name}", "PHASE": phase}
    if recipe_file: env["STAGE_RECIPE"] = f"/recipes/{os.path.basename(recipe_file)}"
    env_args = []
    for k, v in env.items(): env_args += ["-e", f"{k}={v}"]
    cname = f"seqj_{phase}_{uuid.uuid4().hex[:10]}"
    cmd = ["docker", "run", "--rm", "--name", cname,
           "-v", f"{work_dir}:/work/src", "-v", f"{recipes_dir}:/recipes:ro",
           "-v", f"{log_dir}:/out", "--network", NET,
           "-v", f"{M2_CACHE}:/root/.m2",
           "-v", f"{MAVEN_SETTINGS}:/root/.m2/settings.xml:ro",
           "-v", f"{ENTRY}:/entry.sh:ro",
           *env_args, "--entrypoint", "bash", IMAGE, "/entry.sh"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        for c in (["docker", "kill", cname], ["docker", "rm", "-f", cname]):
            try: subprocess.run(c, capture_output=True, timeout=15)
            except Exception: pass
        rc = 124
    log_path = os.path.join(log_dir, log_name)
    log = open(log_path).read() if os.path.exists(log_path) else ""
    return rc, log


def _root_rm(*paths):
    """Reap scratch workdirs as root. docker_phase runs Maven as root inside the
    build container, so each workdir fills with root-owned files; a user-level
    shutil.rmtree hits Permission denied and silently leaks them (this is what
    filled the scratch disk). Per P6, clean docker-owned files through a root
    container, not host rm. All workdirs share one parent (WORK); mount it and
    rm the basenames inside a throwaway root container (the project build image)."""
    paths = [p for p in paths if p and os.path.isdir(p)]
    if not paths:
        return
    parent = os.path.dirname(paths[0])
    names = " ".join("/w/" + os.path.basename(p) for p in paths)
    subprocess.run(["docker", "run", "--rm", "-v", parent + ":/w",
                    "--entrypoint", "sh", IMAGE, "-c", "rm -rf " + names],
                   capture_output=True, timeout=300)


def run_stage(stage):
    repo = stage["repo"]; sha_from = stage["sha_from"]
    jf = stage.get("jv_from", 8); jt = stage.get("jv_to", 21)
    slug = f"{repo.replace('/', '_')}__J{jf}toJ{jt}"
    out_path = f"{OUT_DIR}/{slug}.json"
    if os.path.exists(out_path): return slug, "cached"

    work = tempfile.mkdtemp(prefix="seqj_w_", dir=WORK)
    recipes = tempfile.mkdtemp(prefix="seqj_r_", dir=WORK)
    logs = tempfile.mkdtemp(prefix="seqj_l_", dir=WORK)
    trajectory = {"stage": stage, "started_at": time.time(), "steps": []}
    try:
        if not shallow_fetch(repo, sha_from, work):
            trajectory["error"] = "checkout_failed"
            return slug, "checkout_failed"
        for label, jdk, recipe_list in plan_for(jf, jt):
            rfile = os.path.join(recipes, f"{label}.yml")
            write_recipe_yaml(rfile, f"org.example.seqj.{slug}.{label}", recipe_list)
            rc_r, log_r = docker_phase(work, recipes, logs, "recipe", jdk, recipe_file=rfile, timeout=1200)
            entry = {"step": label, "jdk": jdk, "recipe_count": len(recipe_list),
                     "recipe_rc": rc_r, "recipe_ok": rc_r == 0}
            if rc_r != 0:
                entry["recipe_log_tail"] = log_r[-800:]
            else:
                rc_b, log_b = docker_phase(work, recipes, logs, "build_post", jdk, timeout=600)
                entry["build_rc"] = rc_b
                entry["build_ok"] = rc_b == 0
                if rc_b != 0: entry["build_log_tail"] = log_b[-800:]
            trajectory["steps"].append(entry)
            json.dump(trajectory, open(out_path, "w"), indent=2)
            if not entry["recipe_ok"] or not entry.get("build_ok", True):
                trajectory["aborted_at"] = label
                break
        trajectory["finished_at"] = time.time()
        trajectory["wall_s"] = round(trajectory["finished_at"] - trajectory["started_at"], 1)
        # Final verdict
        all_steps = trajectory["steps"]
        last = all_steps[-1] if all_steps else None
        trajectory["final_status"] = (
            "PASS" if last and last.get("recipe_ok") and last.get("build_ok")
            else "FAIL_at_" + (last.get("step", "?") if last else "no_steps")
        )
    finally:
        json.dump(trajectory, open(out_path, "w"), indent=2)
        _root_rm(work, recipes, logs)
    return slug, trajectory.get("final_status", "?")


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", default=f"{ATTEMPT7}/j8j21_full_sample.json",
                    help="path to JSON list of stages")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    sample = json.load(open(args.sample))
    print(f"running sequenced-java trajectory on {len(sample)} J8→J21 stages")
    print(f"each stage: 7 steps × ~3 min = ~21 min sequential, ~5 min wall at 4 workers\n")
    lock = threading.Lock()
    done = [0]
    def go(s):
        slug, status = run_stage(s)
        with lock:
            done[0] += 1
            print(f"  [{done[0]:2d}/{len(sample)}] {slug}: {status}", flush=True)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(go, sample))

    # Aggregate
    print("\n=== A/B vs iter-0 (UpgradeToJava21 one-shot) ===")
    print(f"  {'stage':<58s}  {'iter-0':<12s}  {'sequenced':<22s}")
    for s in sample:
        jf = s.get("jv_from", 8); jt = s.get("jv_to", 21)
        slug = f"{s['repo'].replace('/', '_')}__J{jf}toJ{jt}"
        p = f"{OUT_DIR}/{slug}.json"
        seq = "?"
        if os.path.exists(p):
            t = json.load(open(p))
            seq = t.get("final_status", "?")
        print(f"  {slug[:58]:<58s}  {s['i0_status']:<12s}  {seq:<22s}")


if __name__ == "__main__":
    main()

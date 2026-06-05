#!/usr/bin/env python3
"""Self-contained reproduction helpers OWNED by the active attempt (attempt_12).

Deliberately has NO cross-attempt imports and NO import-time side effects (unlike
tools/run_sequenced_java.py, whose module body does os.makedirs(attempt_7/sequenced_java)).
Everything it touches is either (a) this attempt's own files (the sibling
run_one_stage_v2.sh, resolved via __file__) or (b) shared infra that is not an
attempt artifact: the j21-fitness build image, the shared ~/.m2-fitness cache, the
maven settings, and the docker network. Test/compile phases go through the SAME
run_one_stage_v2.sh + mounts the production harness uses, so results match sweep verdicts.
"""
import os, re, subprocess, uuid

HERE = os.path.dirname(os.path.abspath(__file__))                 # .../attempt_12/tools
ENTRY = os.path.join(HERE, "run_one_stage_v2.sh")                 # attempt-owned sibling entry
assert os.path.exists(ENTRY), f"missing attempt-owned entry: {ENTRY}"
IMAGE = "j21-fitness:latest"                                      # shared build image (infra)
M2_CACHE = "/home/vmihaylov/.m2-fitness"                          # shared maven cache (infra)
MAVEN_SETTINGS = "/home/vmihaylov/maven-config/settings.xml"      # maven settings (infra)
NET = "mvn-cache"                                                 # docker network (infra)


def shallow_fetch(repo, sha, dst):
    """git init + fetch one sha (self-contained; copy of the harness fetch, no side effects)."""
    url = f"https://github.com/{repo}.git"
    os.makedirs(dst, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=dst, capture_output=True, timeout=30)
    subprocess.run(["git", "remote", "add", "origin", url], cwd=dst, capture_output=True, timeout=10)
    r = subprocess.run(["git", "fetch", "--depth=1", "origin", sha], cwd=dst, capture_output=True, timeout=600)
    if r.returncode != 0:
        r = subprocess.run(["git", "fetch", "origin", sha], cwd=dst, capture_output=True, timeout=900)
    subprocess.run(["git", "checkout", "-q", sha], cwd=dst, capture_output=True, timeout=60)
    return r.returncode == 0


def run_phase(work_dir, log_dir, phase, jdk, timeout=1800):
    """Run the attempt-owned run_one_stage_v2.sh inside the build image, exactly as the
    production harness's docker_phase does. phase in {build_pre,build_post,test_pre,test_post}.
    Returns (rc, log_text)."""
    os.makedirs(log_dir, exist_ok=True)
    log_name = f"{phase}.log"
    env = {"STAGE_JDK": str(jdk), "BUILD_TOOL": "maven", "STAGE_LOG": f"/out/{log_name}", "PHASE": phase}
    env_args = []
    for k, v in env.items():
        env_args += ["-e", f"{k}={v}"]
    cname = f"valid_{phase}_{uuid.uuid4().hex[:10]}"
    cmd = ["docker", "run", "--rm", "--name", cname,
           "-v", f"{work_dir}:/work/src",
           "-v", f"{log_dir}:/out",
           "--network", NET,
           "-v", f"{M2_CACHE}:/root/.m2",
           "-v", f"{MAVEN_SETTINGS}:/root/.m2/settings.xml:ro",
           "-v", f"{ENTRY}:/entry.sh:ro",
           *env_args, "--entrypoint", "bash", IMAGE, "/entry.sh"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=timeout)
        rc = r.returncode
    except subprocess.TimeoutExpired:
        for c in (["docker", "kill", cname], ["docker", "rm", "-f", cname]):
            try:
                subprocess.run(c, capture_output=True, timeout=15)
            except Exception:
                pass
        rc = 124
    lp = os.path.join(log_dir, log_name)
    return rc, (open(lp).read() if os.path.exists(lp) else "")


import glob
import xml.etree.ElementTree as ET


def passing_tests(proj):
    """Authoritative pass set from surefire-reports XML (NOT stdout: the harness runs `mvn -q`
    with defaultLogLevel=warn, which suppresses the 'Tests run:' console lines). A test is
    passing iff its <testcase> has no <failure>/<error>/<skipped> child. Returns set of
    'classname#name'."""
    passed = set()
    for x in glob.glob(os.path.join(proj, "**/target/surefire-reports/TEST-*.xml"), recursive=True):
        try:
            root = ET.parse(x).getroot()
        except Exception:
            continue
        for tc in root.iter("testcase"):
            if any(c.tag in ("failure", "error", "skipped") for c in tc):
                continue
            passed.add(f"{tc.get('classname','')}#{tc.get('name','')}")
    return passed


def clear_reports(proj):
    """Remove every target/surefire-reports dir (root-owned, written by the build container) so a
    later phase's pass set can't be contaminated by stale XML from an earlier phase/JDK."""
    subprocess.run(["docker", "run", "--rm", "-v", f"{proj}:/w", "--entrypoint", "sh", IMAGE,
                    "-c", "find /w -path '*/target/surefire-reports' -type d -exec rm -rf {} + 2>/dev/null; true"],
                   capture_output=True, timeout=120)

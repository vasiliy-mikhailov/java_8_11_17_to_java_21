#!/usr/bin/env python3
"""Validate the java11_compat surefire floor using ONLY current-attempt (attempt_12) files:
 - fetch + harness test phases via the attempt-owned repro_lib / run_one_stage_v2.sh
 - bump via the attempt-owned scripts/bump_8_to_11.sh
Reports, per repo: did the surefire floor FIRE, bump rc, pre/post pass counts, CONSERVED/REGRESSED.
Run from the attempt: python3 attempt_12/tools/validate_surefire.py
"""
import os, sys, json, glob, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))      # attempt_12/tools
ATTEMPT = os.path.dirname(HERE)                        # attempt_12
sys.path.insert(0, HERE)
from repro_lib import shallow_fetch, run_phase, passing_tests, clear_reports

BUMP = os.path.join(ATTEMPT, ".agents/skills/bump-java-version/scripts/bump_8_to_11.sh")
PRI = os.path.join(ATTEMPT, "per_repo_iter")
WORKBASE = "/tmp/valid_surefire"
assert os.path.exists(BUMP), f"missing attempt bump script: {BUMP}"


def run_bump(workdir, logpath):
    env = dict(os.environ)
    env["PATH"] = "/home/vmihaylov/bin:" + env.get("PATH", "")   # host mvn wrapper (infra)
    r = subprocess.run(["bash", BUMP, workdir], capture_output=True, timeout=3000, env=env)
    blob = r.stdout + b"\n---STDERR---\n" + r.stderr
    open(logpath, "wb").write(blob)
    return r.returncode, blob.decode("utf-8", "replace")


def sha_for(repo):
    slug = repo.replace("/", "_")
    for d in sorted(glob.glob(os.path.join(PRI, slug + "_*"))):
        tj = os.path.join(d, "trajectory.json")
        if os.path.exists(tj):
            try:
                return json.load(open(tj))["stage"]["sha_from"]
            except Exception:
                pass
    return None


def one(repo, sha, jv_from=8, jv_to=11, proj_sub=None):
    slug = repo.replace("/", "_")
    work = os.path.join(WORKBASE, slug)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    if not shallow_fetch(repo, sha, work):
        print(f"{repo}: FETCH_FAILED"); return
    proj = os.path.join(work, proj_sub) if proj_sub else work
    logd = os.path.join(work, "_logs")
    rc_pre, _ = run_phase(proj, logd, "test_pre", jv_from)
    pre = passing_tests(proj)                 # authoritative: surefire XML
    clear_reports(proj)                       # so post can't read stale pre XML
    brc, blog = run_bump(proj, os.path.join(logd, "bump.log"))
    fired = "surefire floor applied" in blog
    rc_post, _ = run_phase(proj, logd, "test_post", jv_to)
    post = passing_tests(proj)
    lost = sorted(pre - post)                  # baseline-pass tests missing post-bump = real regressions
    cons = "CONSERVED" if not lost else f"REGRESSED({len(lost)})"
    print(f"{repo}: floor={'FIRED' if fired else 'noop'} bump_rc={brc} "
          f"pre_pass={len(pre)}(rc={rc_pre}) post_pass={len(post)}(rc={rc_post}) -> {cons}"
          + (f"  lost[:3]={lost[:3]}" if lost else ""))


print("######## END-TO-END FIX: in28 spring-boot-2-jdbc-with-h2 ########")
one("in28minutes/spring-boot-examples", "6db697ee4cd41034f7fe0048e29184a1df71bbd7",
    proj_sub="spring-boot-2-jdbc-with-h2")

print("######## REGRESSION SWEEP (curated green 8->11) ########")
GREEN = ["andrei-punko/spring-boot-2-jsonb", "making/oauth2-sso-demo",
         "daggerok/distributed-lock-mongodb-spring-boot-starter",
         "hendisantika/spring-thymeleaf-pagination", "ozimov/spring-boot-email-tools",
         "encircled/Joiner", "red6/dmn-check", "a-oleynik/junit-workshop",
         "dschadow/JavaSecurity", "develproper/ewqewq"]
for repo in GREEN:
    sha = sha_for(repo)
    if not sha:
        print(f"{repo}: NO_SHA_IN_PER_REPO_ITER"); continue
    one(repo, sha)
print("VALIDATE_DONE")

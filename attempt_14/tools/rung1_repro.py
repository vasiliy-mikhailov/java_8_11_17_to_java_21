#!/usr/bin/env python3
"""Deterministic rung-1 reproduction using ONLY current_attempt files: fetch, test_pre(jv_from),
the attempt's bump_<jf>_to_<jt>.sh, test_post(jv_to); report conservation (pre-pass set vs post)
from the authoritative surefire-reports XML. Lives under current_attempt/tools, imports the
sibling repro_lib (resolve via __file__, never a hardcoded attempt path).

Usage: python3 rung1_repro.py <repo> <sha> <jv_from> <jv_to> [proj_sub]
"""
import os, sys, shutil, subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ATTEMPT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from repro_lib import shallow_fetch, run_phase, passing_tests, clear_reports

SCRIPTS = os.path.join(ATTEMPT, ".agents/skills/bump-java-version/scripts")


def main():
    repo, sha, jf, jt = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
    proj_sub = sys.argv[5] if len(sys.argv) > 5 else None
    bump = os.path.join(SCRIPTS, f"bump_{jf}_to_{jt}.sh")
    assert os.path.exists(bump), f"no attempt bump script: {bump}"
    work = f"/tmp/rung1_{repo.replace('/', '_')}"
    # Build phases run Maven as root in the container, leaving root-owned files a host-user
    # rmtree cannot delete (P6). Clear via a throwaway root container before reusing the dir.
    import repro_lib
    subprocess.run(["docker", "run", "--rm", "-v", "/tmp:/t", "--entrypoint", "sh", repro_lib.IMAGE,
                    "-c", f"rm -rf /t/{os.path.basename(work)}"], capture_output=True, timeout=120)
    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work, exist_ok=True)
    if not shallow_fetch(repo, sha, work):
        print("FETCH_FAILED"); return
    proj = os.path.join(work, proj_sub) if proj_sub else work
    logd = os.path.join(work, "_logs")

    rc_pre, _ = run_phase(proj, logd, "test_pre", jf)
    pre = passing_tests(proj)
    clear_reports(proj)

    env = dict(os.environ)
    env["PATH"] = "/home/vmihaylov/bin:" + env.get("PATH", "")
    br = subprocess.run(["bash", bump, proj], capture_output=True, timeout=3000, env=env)
    open(os.path.join(logd, "bump.log"), "wb").write(br.stdout + b"\n--STDERR--\n" + br.stderr)
    blog = (br.stdout + br.stderr).decode("utf-8", "replace")

    rc_post, _ = run_phase(proj, logd, "test_post", jt)
    post = passing_tests(proj)

    lost = sorted(pre - post)
    gained = sorted(post - pre)
    print(f"{repo} {jf}->{jt}: bump_rc={br.returncode} rc_pre={rc_pre} rc_post={rc_post} "
          f"surefire_floor={'FIRED' if 'surefire floor applied' in blog else 'noop'}")
    print(f"  pre_pass={len(pre)} post_pass={len(post)} lost={len(lost)} gained={len(gained)} "
          f"-> {'CONSERVED' if not lost else 'REGRESSED'}")
    for t in lost:
        print(f"  LOST: {t}")
    print("RUNG1_DONE")


if __name__ == "__main__":
    main()

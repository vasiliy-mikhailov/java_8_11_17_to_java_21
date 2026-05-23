"""Verify v3 lineage candidates. Higher concurrency (16) per fitness #8.
Reads /tmp/lineage_candidates_v3.json.
"""
import json, os, subprocess, threading, tempfile, shutil
from concurrent.futures import ThreadPoolExecutor

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
CANDIDATES = "/tmp/lineage_candidates_v3.json"


def verify_one_commit(repo_url, sha, jv):
    tmp = tempfile.mkdtemp(prefix="lv3-")
    try:
        r = subprocess.run(["git","clone","--filter=blob:none","--no-checkout",repo_url,f"{tmp}/src"],
                           capture_output=True, timeout=120)
        if r.returncode != 0: return False
        subprocess.run(["git","fetch","--depth","50","origin",sha], cwd=f"{tmp}/src",
                       capture_output=True, timeout=120)
        r = subprocess.run(["git","checkout","--detach",sha], cwd=f"{tmp}/src",
                           capture_output=True, timeout=30)
        if r.returncode != 0: return False
        root = f"{tmp}/src"
        if not os.path.exists(f"{root}/pom.xml"):
            for r2,_,f in os.walk(root):
                if "pom.xml" in f: root = r2; break
        if not os.path.exists(f"{root}/pom.xml"): return False
        jdk_path = f"/opt/jdk/{jv}"
        cmd = ("mvn -B -q -ntp -fae -Denforcer.skip=true -DskipTests "
               "-Dlombok.version=1.18.36 -Dmaven.javadoc.skip=true -Dcheckstyle.skip=true "
               "-Dspotbugs.skip=true -Dspring-javaformat.skip=true -Dformat.skip=true compile")
        home = os.environ["HOME"]
        cname = f"lv3-{os.getpid()}-{threading.get_ident()}"
        docker_cmd = ["docker","run","--rm","--name",cname,"--cpus","2.5","--memory","6g",
                      "--entrypoint","/bin/bash",
                      "-v", f"{root}:/work",
                      "-v", f"{home}/.m2-fitness:/root/.m2",
                      "-e", f"JAVA_HOME={jdk_path}",
                      "-e", f"PATH={jdk_path}/bin:/opt/maven/bin:/usr/local/bin:/usr/bin:/bin",
                      "-w","/work","j21-fitness:latest","-c", cmd]
        try:
            r = subprocess.run(docker_cmd, capture_output=True, timeout=600)
            return r.returncode == 0
        except subprocess.TimeoutExpired:
            subprocess.run(["docker","kill",cname], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            return False
    except Exception:
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    cands = json.load(open(CANDIDATES))
    j21 = [c for c in cands if c["newest_java_version"] == 21]
    print(f"candidates reaching J21: {len(j21)}", flush=True)

    sem = threading.BoundedSemaphore(16)
    verified = []
    lock = threading.Lock()
    done = [0]

    def worker(lin):
        repo_url = f"https://github.com/{lin['repo_full_name']}.git"
        per = []
        ok = True
        for step in lin["lineage"]:
            with sem:
                bp = verify_one_commit(repo_url, step["commit_sha"], step["java_version"])
            per.append({"java_version": step["java_version"], "commit_sha": step["commit_sha"], "build_pass": bp})
            if not bp: ok = False
        with lock:
            done[0] += 1
            entry = {**lin, "verified_lineage": per, "all_pass": ok}
            verified.append(entry)
            if done[0] % 10 == 0:
                fp = sum(1 for e in verified if e["all_pass"])
                print(f"  verified {done[0]}/{len(j21)}, full-pass={fp}", flush=True)
                # checkpoint partial output
                with open("/tmp/lineage_verified_v3.partial.json", "w") as f:
                    json.dump(verified, f)

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(worker, j21))

    out_all = f"{HERE}/attempt_5/lineage_verified_v3.json"
    json.dump(verified, open(out_all, "w"), indent=2)
    full = [e for e in verified if e["all_pass"]]
    out = f"{HERE}/attempt_5/lineage_dataset_v3.json"
    json.dump(full, open(out, "w"), indent=2)
    print(f"\nfull-pass: {len(full)}, saved to {out}")


if __name__ == "__main__":
    main()

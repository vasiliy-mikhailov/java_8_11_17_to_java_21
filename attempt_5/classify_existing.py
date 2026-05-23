"""Post-hoc cluster classification for v1+v2 lineage dataset entries.
Re-clones each repo, reads pom.xml at oldest commit, detects dep family.
"""
import json, os, re, subprocess, tempfile, shutil, threading
from concurrent.futures import ThreadPoolExecutor

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"

FAMILY = {
    "hibernate-5": [
        re.compile(r"<artifactId>hibernate-core</artifactId>\s*<version>5\."),
        re.compile(r"<hibernate\.version>5\."),
    ],
    "jakarta-ee-javax": [
        re.compile(r"<artifactId>javax\.servlet-api</artifactId>"),
        re.compile(r"<artifactId>javax\.persistence-api</artifactId>"),
        re.compile(r"<groupId>javax\.servlet"),
        re.compile(r"<groupId>javax\.persistence"),
    ],
    "junit4-mockito": [
        re.compile(r"<artifactId>junit</artifactId>\s*<version>4\."),
        re.compile(r"<artifactId>mockito-core</artifactId>"),
        re.compile(r"<artifactId>mockito-all</artifactId>"),
    ],
    "spring-boot-2": [
        re.compile(r"<artifactId>spring-boot-starter-parent</artifactId>\s*<version>2\."),
        re.compile(r"<spring-boot\.version>2\."),
    ],
}

def detect_family(pom):
    for fam, pats in FAMILY.items():
        for p in pats:
            if p.search(pom):
                return fam
    return None


def get_pom_at(repo_full, sha):
    tmp = tempfile.mkdtemp(prefix="cl-")
    try:
        url = f"https://github.com/{repo_full}.git"
        r = subprocess.run(["git","clone","--filter=blob:none","--no-checkout",url,f"{tmp}/r"],
                           capture_output=True, timeout=60)
        if r.returncode != 0:
            return None
        subprocess.run(["git","fetch","--depth","2","origin",sha], cwd=f"{tmp}/r",
                       capture_output=True, timeout=60)
        # list pom files at the sha
        r = subprocess.run(["git","ls-tree","-r","--name-only",sha], cwd=f"{tmp}/r",
                           capture_output=True, timeout=15)
        if r.returncode != 0:
            return None
        poms = [p for p in r.stdout.decode().split() if p.endswith("pom.xml")][:5]
        # concatenate first 5 pom files (covers root + few modules)
        out = ""
        for p in poms:
            rr = subprocess.run(["git","show",f"{sha}:{p}"], cwd=f"{tmp}/r",
                                capture_output=True, timeout=10)
            if rr.returncode == 0:
                out += rr.stdout.decode(errors="replace") + "\n"
        return out
    except Exception:
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    v1 = json.load(open(f"{HERE}/attempt_5/lineage_dataset.json"))
    v2 = json.load(open(f"{HERE}/attempt_5/lineage_dataset_v2.json"))
    seen = {}
    for l in v1 + v2:
        seen[l["repo_full_name"]] = l
    data = list(seen.values())
    print(f"classifying {len(data)} entries", flush=True)

    sem = threading.BoundedSemaphore(16)
    lock = threading.Lock()
    done = [0]

    def worker(e):
        oldest = min(e["verified_lineage"], key=lambda s: s["java_version"])
        pom = None
        with sem:
            pom = get_pom_at(e["repo_full_name"], oldest["commit_sha"])
        fam = detect_family(pom) if pom else None
        with lock:
            done[0] += 1
            e["family_at_oldest"] = fam
            if done[0] % 10 == 0:
                print(f"  {done[0]}/{len(data)}", flush=True)

    with ThreadPoolExecutor(max_workers=20) as ex:
        list(ex.map(worker, data))

    out = f"{HERE}/attempt_5/lineage_dataset_classified.json"
    json.dump(data, open(out, "w"), indent=2)

    import collections
    by_cell = collections.Counter((e["oldest_java_version"], e["family_at_oldest"]) for e in data)
    print(f"\nclassified by (oldest_java, family):")
    for k in sorted(by_cell, key=lambda x: (x[0], x[1] or "zz")):
        print(f"  {k}: {by_cell[k]}")
    print(f"\nsaved to {out}")


if __name__ == "__main__":
    main()

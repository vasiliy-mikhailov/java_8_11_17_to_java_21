"""Run fitness function #4 in attempt_6: emit per-(repo, stage) human-intent extracts
across the full corpus, using cached repo mirrors. Auto-prewarms /var/cache/git-mirrors/."""
import json, os, subprocess, threading, urllib.request, re, time
from concurrent.futures import ThreadPoolExecutor

CORPUS = "/home/vmihaylov/java_8_11_17_to_java_21/attempt_5/lineage_dataset_v4_final.json"
OUT_ROOT = "/home/vmihaylov/java_8_11_17_to_java_21/attempt_6/intent_samples"
CACHE_ROOT = "/var/cache/git-mirrors"
os.makedirs(OUT_ROOT, exist_ok=True)
os.makedirs(CACHE_ROOT, exist_ok=True)

SYSTEM = """You extract HUMAN INTENTS from a unified diff between two commits of the same repo.
Older commit on '-' side, newer on '+' side. The author moved this code from one Java version to the next.

For each distinct INTENT (the purpose of a change, not its surface text), emit one JSON atom:
{
  "kind":         "<short snake_case label>",
  "general_idea": "<one sentence describing the migration purpose>",
  "human_impl":   "<brief concrete snippet showing what was done>",
  "bucket":       "breaking | polishment"
}

CRITICAL RULES:
1) Atomicity: each atom = ONE atomic change. 6 added dependencies = 6 atoms, not 1.
2) bucket=breaking ONLY if the migration won't compile or run on the target JDK without this change.
3) bucket=polishment for cosmetic renames, optional feature deps, build-plugin minor bumps already
   compatible with the old JDK, restructuring, doc/test modernisation that wasn't required to compile.
4) Default to polishment when in doubt.
5) Skip pure whitespace/comment-only changes unless they signal real intent.

Output ONLY a JSON array. No prose, no markdown."""


cache_lock = threading.Lock()
cache_locks = {}  # per-repo lock

def get_repo_lock(repo):
    with cache_lock:
        if repo not in cache_locks:
            cache_locks[repo] = threading.Lock()
        return cache_locks[repo]


def ensure_mirror(repo):
    """Clone --mirror to /var/cache/git-mirrors/<owner>/<repo>.git if not present."""
    owner, name = repo.split("/", 1)
    mirror_dir = os.path.join(CACHE_ROOT, owner, f"{name}.git")
    if os.path.exists(os.path.join(mirror_dir, "HEAD")):
        return mirror_dir
    with get_repo_lock(repo):
        if os.path.exists(os.path.join(mirror_dir, "HEAD")):
            return mirror_dir
        os.makedirs(os.path.dirname(mirror_dir), exist_ok=True)
        url = f"https://github.com/{repo}.git"
        r = subprocess.run(["git","clone","--mirror","--filter=blob:none",url,mirror_dir],
                           capture_output=True, timeout=600)
        if r.returncode != 0:
            return None
        return mirror_dir


def ensure_sha(mirror_dir, sha):
    """Make sure sha is fetched into the mirror."""
    r = subprocess.run(["git","--git-dir",mirror_dir,"cat-file","-e",sha],
                       capture_output=True, timeout=10)
    if r.returncode == 0:
        return True
    # Try fetching
    r = subprocess.run(["git","--git-dir",mirror_dir,"fetch","--depth","200","origin",sha],
                       capture_output=True, timeout=120)
    if r.returncode != 0:
        # Try unshallow
        subprocess.run(["git","--git-dir",mirror_dir,"fetch","--unshallow","origin"],
                       capture_output=True, timeout=600)
    r = subprocess.run(["git","--git-dir",mirror_dir,"cat-file","-e",sha],
                       capture_output=True, timeout=10)
    return r.returncode == 0


def gen_human_diffs(repo, sha_from, sha_to):
    mirror = ensure_mirror(repo)
    if mirror is None: return None, None
    if not ensure_sha(mirror, sha_from): return None, None
    if not ensure_sha(mirror, sha_to): return None, None
    log_p = subprocess.run(["git","--git-dir",mirror,"log","--oneline","--no-decorate",f"{sha_from}..{sha_to}"],
                           capture_output=True, timeout=30)
    commit_log = log_p.stdout.decode(errors="replace").strip()
    ns = subprocess.run(["git","--git-dir",mirror,"diff","--name-status",sha_from,sha_to],
                        capture_output=True, timeout=60)
    name_status = ns.stdout.decode(errors="replace").strip().splitlines()
    modified = [ln.split(maxsplit=1)[1] for ln in name_status if ln.startswith("M\t") or ln.startswith("M ")]
    modified.sort(key=lambda x: (0 if x.endswith(".java") else 1 if x.endswith("pom.xml") else 2, x))
    diffs = {}
    for rel in modified[:12]:
        r = subprocess.run(["git","--git-dir",mirror,"diff",sha_from,sha_to,"--",rel],
                           capture_output=True, timeout=20)
        text = r.stdout.decode(errors="replace")
        if text.strip(): diffs[rel] = text  # no pre-truncation; ask_qwen hunk-splits
    return commit_log, diffs


def split_diff_by_hunks(diff_text, chunk_char_cap=40000):
    """Split a unified diff into chunks at hunk boundaries (@@ ... @@), each <= chunk_char_cap.
    The file header (everything before first @@) is repeated in each chunk so the LLM sees
    which file each hunk belongs to. Binary diffs and degenerate cases fall back to slicing."""
    lines = diff_text.split("\n")
    hunk_starts = [i for i, l in enumerate(lines) if l.startswith("@@ ")]
    if not hunk_starts:
        return [diff_text[i:i+chunk_char_cap] for i in range(0, max(1, len(diff_text)), chunk_char_cap)]
    header = "\n".join(lines[:hunk_starts[0]])
    hunks = []
    for i, st in enumerate(hunk_starts):
        end = hunk_starts[i+1] if i+1 < len(hunk_starts) else len(lines)
        hunks.append("\n".join(lines[st:end]))
    chunks, cur = [], header
    for h in hunks:
        candidate = cur + "\n" + h if cur != header else cur + "\n" + h
        if cur != header and len(cur) + 1 + len(h) > chunk_char_cap:
            chunks.append(cur); cur = header + "\n" + h
        else:
            cur = (cur + "\n" + h) if cur else h
    if cur and cur != header: chunks.append(cur)
    return chunks or [diff_text[:chunk_char_cap]]


def _post_qwen(diff_chunk, file_path, jv_from, jv_to, log_section):
    user = f"File: {file_path}\nStage: J{jv_from} -> J{jv_to}{log_section}\n\nDIFF:\n{diff_chunk}"
    body = {"model":"qwen3.6-27b-fp8","messages":[
            {"role":"system","content":SYSTEM},
            {"role":"user","content":user}],
            "temperature":0.0,"max_tokens":16000,"chat_template_kwargs":{"enable_thinking":False}}
    req = urllib.request.Request("http://localhost:8000/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization":"Bearer sk-ef2926520a83b7f6efac7f4dc5b049842b4b2baebfdc18b69b76220f29fdf272","Content-Type":"application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                content = (json.loads(r.read())["choices"][0]["message"].get("content") or "").strip()
            m = re.search(r"\[.*\]", content, re.DOTALL)
            return json.loads(m.group(0)) if m else []
        except Exception:
            if attempt == 2: return []
            time.sleep(2 ** attempt)


def ask_qwen(file_path, jv_from, jv_to, diff_text, commit_log):
    log_section = ("\nGIT LOG (commits between snapshots):\n" + commit_log[:2000]) if commit_log else ""
    chunks = split_diff_by_hunks(diff_text, chunk_char_cap=40000)
    all_intents = []
    for ch in chunks:
        intents = _post_qwen(ch, file_path, jv_from, jv_to, log_section) or []
        all_intents.extend(intents)
    return all_intents


def commit_progress(n_done):
    """Incremental git commit."""
    try:
        subprocess.run(["docker","run","--rm","-v","/home/vmihaylov/java_8_11_17_to_java_21:/w","alpine:3","chown","-R","1000:1000","/w"], capture_output=True, timeout=30)
        subprocess.run(["git","-C","/home/vmihaylov/java_8_11_17_to_java_21","add","attempt_6/intent_samples"], capture_output=True, timeout=30)
        subprocess.run(["git","-C","/home/vmihaylov/java_8_11_17_to_java_21","-c","user.email=agent@mh","-c","user.name=agent","commit","-m",f"attempt_6 fitness #4: {n_done} stages of human-intent extracts"], capture_output=True, timeout=30)
        subprocess.run(["git","-C","/home/vmihaylov/java_8_11_17_to_java_21","push","origin","main"], capture_output=True, timeout=60)
    except Exception:
        pass


def main():
    corpus = json.load(open(CORPUS))
    stages = []
    for e in corpus:
        steps = sorted(e["verified_lineage"], key=lambda s: s["java_version"])
        for i in range(len(steps) - 1):
            stages.append({
                "repo": e["repo_full_name"],
                "sha_from": steps[i]["commit_sha"],
                "sha_to":   steps[i+1]["commit_sha"],
                "jv_from": steps[i]["java_version"],
                "jv_to":   steps[i+1]["java_version"],
                "family":  e.get("family_at_oldest"),
            })
    print(f"total stages: {len(stages)}; unique repos: {len({s['repo'] for s in stages})}", flush=True)

    done = set()
    for slug in os.listdir(OUT_ROOT) if os.path.exists(OUT_ROOT) else []:
        if os.path.exists(f"{OUT_ROOT}/{slug}/intents.json"):
            # slug is repo_safe__JfromtoJto
            done.add(slug)
    print(f"resume: {len(done)} stage dirs already done", flush=True)

    sem = threading.BoundedSemaphore(6)
    lock = threading.Lock()
    done_ct = [0]

    def process(p):
        slug = f"{p['repo'].replace('/','_')}__J{p['jv_from']}toJ{p['jv_to']}"
        out_sub = f"{OUT_ROOT}/{slug}"
        if slug in done:
            with lock: done_ct[0] += 1
            return
        os.makedirs(out_sub, exist_ok=True)
        with sem:
            commit_log, diffs = gen_human_diffs(p["repo"], p["sha_from"], p["sha_to"])
        if diffs is None:
            with lock:
                done_ct[0] += 1
                print(f"  [{done_ct[0]}/{len(stages)}] FAIL clone/fetch {p['repo']}", flush=True)
            return
        if not diffs:
            with lock:
                done_ct[0] += 1
                print(f"  [{done_ct[0]}/{len(stages)}] no MODIFIED files {p['repo']}", flush=True)
            with open(f"{out_sub}/intents.json", "w") as f:
                json.dump({"meta":{"repo":p["repo"],"stage":f"J{p['jv_from']}->J{p['jv_to']}",
                                  "family":p.get("family"),"sha_from":p["sha_from"],"sha_to":p["sha_to"]},
                           "by_file":{}}, f, indent=2)
            return
        for rel, dt in diffs.items():
            with open(f"{out_sub}/{rel.replace('/','__')}.diff", "w") as f:
                f.write(dt)
        with open(f"{out_sub}/commit_log.txt", "w") as f:
            f.write(commit_log or "(empty)")
        all_int = {}
        n_int = 0
        for rel, dt in diffs.items():
            intents = ask_qwen(rel, p["jv_from"], p["jv_to"], dt, commit_log)
            all_int[rel] = intents
            n_int += len(intents)
        with open(f"{out_sub}/intents.json", "w") as f:
            json.dump({"meta":{"repo":p["repo"],"stage":f"J{p['jv_from']}->J{p['jv_to']}",
                              "family":p.get("family"),"sha_from":p["sha_from"],"sha_to":p["sha_to"]},
                       "by_file":all_int}, f, indent=2)
        with lock:
            done_ct[0] += 1
            jv_files = sum(1 for k in diffs if k.endswith(".java"))
            print(f"  [{done_ct[0]}/{len(stages)}] +{p['repo'][:40]:<40} J{p['jv_from']}->J{p['jv_to']} files={len(diffs)} java={jv_files} intents={n_int}", flush=True)
            if done_ct[0] % 50 == 0:
                commit_progress(done_ct[0])

    with ThreadPoolExecutor(max_workers=10) as ex:
        list(ex.map(process, stages))

    commit_progress(done_ct[0])
    print(f"\nDONE: {done_ct[0]} stages processed", flush=True)


if __name__ == "__main__":
    main()

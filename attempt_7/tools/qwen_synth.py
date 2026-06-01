"""attempt_7 Qwen-driven synthesizer.

For each stage under attempt_7/per_stage/<slug>/ that has diff.txt + meta.json:
  - Build sharp prompt (compat matrix + diff + REQUIRED-only instructions)
  - Call Qwen
  - Extract YAML recipe
  - Save recipe_qwen.yaml
  - Verify by applying + mvn compile under jv_to → verdict_qwen.json

A/B comparison: subagent verdicts are in verdict.json, qwen verdicts in verdict_qwen.json.

Usage:
  qwen_synth_attempt7.py [--limit N] [--slug-glob 'pattern*'] [--workers 4]
"""
import os, sys, json, glob, subprocess, argparse, threading, time
import urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

BASE = "/home/vmihaylov/java_8_11_17_to_java_21"
ATTEMPT7 = f"{BASE}/attempt_7"
COMPAT_MATRIX = open(f"{ATTEMPT7}/COMPAT_MATRIX.md").read()


def load_env(path=f"{BASE}/.env"):
    env = {}
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env

ENV = load_env()
PROPOSER_URL = ENV.get("PROPOSER_BASE_URL", "https://inference.mikhailov.tech/v1")
PROPOSER_KEY = ENV.get("PROPOSER_API_KEY", "")
PROPOSER_MODEL = ENV.get("PROPOSER_MODEL", "qwen3.6-27b-fp8")


SYSTEM_PROMPT = """You author OpenRewrite recipe YAML files. Your job: given a git diff representing a human-authored Java migration commit and the target Java version, emit a recipe that captures ONLY the changes REQUIRED to make the project build under the target JDK — nothing else.

A change is REQUIRED iff applying jv_to would break the build without it. Use the supplied compatibility matrix to decide.

Allowed OpenRewrite primitives (full FQN must appear in recipeList):
  org.openrewrite.maven.ChangePropertyValue           (key, newValue)
  org.openrewrite.maven.AddProperty                   (key, value)
  org.openrewrite.maven.UpgradeParentVersion          (groupId, artifactId, newVersion)
  org.openrewrite.maven.ChangeParentPom               (oldGroupId, oldArtifactId, newGroupId, newArtifactId, newVersion)
  org.openrewrite.maven.AddDependency                 (groupId, artifactId, version, scope?, type?)
  org.openrewrite.maven.RemoveDependency              (groupId, artifactId)
  org.openrewrite.maven.AddManagedDependency          (groupId, artifactId, version, type?, scope?)
  org.openrewrite.maven.RemoveManagedDependency       (groupId, artifactId)
  org.openrewrite.maven.UpgradeDependencyVersion      (groupId, artifactId, newVersion)
  org.openrewrite.maven.UpgradePluginVersion          (groupId, artifactId, newVersion)
  org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_{0,1,2,3,4,5,6,7}
  org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_{0,1,2,3,4}
  org.openrewrite.java.ChangePackage                  (oldPackageName, newPackageName)
  org.openrewrite.java.ChangeType                     (oldFullyQualifiedTypeName, newFullyQualifiedTypeName)
  org.openrewrite.java.ChangeMethodName               (methodPattern, newMethodName)

Recipe YAML format (MUST match):

---
type: specs.openrewrite.org/v1beta/recipe
name: org.example.required.<slug>
recipeList:
  - org.openrewrite.maven.ChangePropertyValue:
      key: java.version
      newValue: "21"

Rules:
  - Output ONLY the YAML. No prose, no code fences (no triple backticks), no per-line backticks, no commentary.
  - The first line must be exactly `---`. The next non-empty line must start with `type: specs.openrewrite.org/v1beta/recipe`.
  - Quote string values when they contain dots, slashes, or special chars; integers/versions like "21", "2.7.18" must be strings.
  - Do NOT invent primitives not in the list above.
  - Do NOT include orthogonal changes (new features, IDE configs, READMEs, lockfiles, new modules, code refactors, tests, formatting). Skip them silently.
  - If the diff has no REQUIRED changes (e.g., the human added an unrelated feature), emit an empty recipeList: `recipeList: []`.
"""

COMPAT_MATRIX_PROMPT = "\n\n=== COMPATIBILITY MATRIX (decides what's REQUIRED) ===\n" + COMPAT_MATRIX


def _call_qwen(slug, meta, diff, *, enable_thinking, max_tokens):
    user = (
        f"Stage slug: {slug}\n"
        f"Repo: {meta['repo']}\n"
        f"jv_from={meta['jv_from']}  jv_to={meta['jv_to']}\n\n"
        f"{COMPAT_MATRIX_PROMPT}\n\n"
        f"=== GIT DIFF (sha_from..sha_to) ===\n```diff\n{diff}\n```\n\n"
        "Emit the OpenRewrite recipe YAML now. Recipe name MUST be "
        f"org.example.required.{slug}"
    )
    payload = {
        "model": PROPOSER_MODEL,
        "temperature": 0.0,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ],
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }
    req = urllib.request.Request(
        f"{PROPOSER_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {PROPOSER_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code} {e.reason}: {e.read().decode(errors='replace')[:400]}"
    except Exception as e:
        return None, f"{type(e).__name__} {e}"
    return data["choices"][0]["message"]["content"], None


def ask_qwen(slug, meta, diff):
    """Try thinking-mode first; on parse failure fallback to no-thinking."""
    text, err = _call_qwen(slug, meta, diff, enable_thinking=True, max_tokens=32768)
    if err: return None, err, "thinking_err"
    yml = ensure_yaml_or_none(text)
    if yml is not None: return text, None, "thinking"
    # fallback: thinking rambled or produced unparseable output
    text2, err2 = _call_qwen(slug, meta, diff, enable_thinking=False, max_tokens=8192)
    if err2: return text, None, f"thinking_unparseable_no-think_err:{err2[:80]}"
    yml2 = ensure_yaml_or_none(text2)
    if yml2 is not None: return text2, None, "no-think_fallback"
    # both failed
    return text2, None, "both_unparseable"


def extract_yaml(text):
    """Find the recipe YAML in text — permissive.
    Handles bare YAML, ```yaml ``` fences, per-line backtick wrapping,
    reasoning prose interleaved with YAML, and uniformly-indented YAML
    (qwen sometimes prefixes every line with 2 spaces).
    Returns None if no valid root YAML found (caller should fallback).
    """
    import re, textwrap
    text = (text or "").replace("</think>", "").replace("<think>", "")
    if re.search(r"^\s*`[^`\n]+`\s*$", text, re.MULTILINE):
        text = re.sub(r"^\s*`([^`\n]*)`\s*$", r"\1", text, flags=re.MULTILINE)
    fences = list(re.finditer(r"```(?:yaml|yml)?\s*\n(.*?)```", text, re.DOTALL))
    if fences: text = fences[-1].group(1)
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip() == "---":
            for j in range(i + 1, min(len(lines), i + 6)):
                if lines[j].strip().startswith("type:") and "openrewrite.org" in lines[j]:
                    block = "\n".join(lines[i:])
                    # If the whole block is uniformly indented (e.g. 2 spaces on every line),
                    # dedent it — root YAML document must start at column 0.
                    block = textwrap.dedent(block).strip("\n") + "\n"
                    return block
    return None


def ensure_yaml_or_none(text):
    yml = extract_yaml(text)
    if yml is None: return None
    if "type: specs.openrewrite.org/v1beta/recipe" not in yml: return None
    return yml


def verify(slug, stage_dir, meta):
    repo = meta["repo"]; sha_from = meta["sha_from"]; jv_to = meta["jv_to"]
    recipe_path = os.path.join(stage_dir, "recipe_qwen.yaml")
    verdict_path = os.path.join(stage_dir, "verdict_qwen.json")
    r = subprocess.run(
        ["python3", f"{ATTEMPT7}/tools/verify_recipe_builds.py",
         repo, sha_from, str(jv_to), recipe_path, "--out-verdict", verdict_path],
        capture_output=True, timeout=1800,
    )
    return r.returncode, r.stderr.decode(errors="replace")[-500:]


def process_stage(stage_dir):
    slug = os.path.basename(stage_dir.rstrip("/"))
    diff_path = os.path.join(stage_dir, "diff.txt")
    meta_path = os.path.join(stage_dir, "meta.json")
    recipe_path = os.path.join(stage_dir, "recipe_qwen.yaml")
    verdict_path = os.path.join(stage_dir, "verdict_qwen.json")
    if not (os.path.exists(diff_path) and os.path.exists(meta_path)):
        return slug, "no_inputs"
    if os.path.exists(verdict_path):
        return slug, "cached"
    meta = json.load(open(meta_path))
    diff = open(diff_path).read()
    if len(diff) > 400_000:
        return slug, f"diff_too_big ({len(diff)})"
    t0 = time.time()
    text, err, mode = ask_qwen(slug, meta, diff)
    qwen_dt = time.time() - t0
    # Always save raw text for debugging
    if text is not None:
        open(os.path.join(stage_dir, "recipe_qwen.raw.txt"), "w").write(text)
    if err:
        open(verdict_path, "w").write(json.dumps({"slug": slug, "qwen_error": err, "qwen_mode": mode}, indent=2))
        return slug, f"qwen_err: {err[:100]}"
    yml = ensure_yaml_or_none(text)
    if yml is None:
        open(verdict_path, "w").write(json.dumps({"slug": slug, "qwen_error": "no_parseable_yaml", "qwen_mode": mode}, indent=2))
        return slug, f"unparseable (mode={mode}, qwen {qwen_dt:.1f}s)"
    open(recipe_path, "w").write(yml)
    rc, log = verify(slug, stage_dir, meta)
    return slug, f"verified rc={rc} (mode={mode}, qwen {qwen_dt:.1f}s)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--slug-glob", default="*")
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    stages = sorted(glob.glob(f"{ATTEMPT7}/per_stage/{args.slug_glob}/"))
    # only the stages we already processed with subagents (have verdict.json)
    have_subagent_verdict = [d for d in stages if os.path.exists(os.path.join(d, "verdict.json"))]
    print(f"stages with subagent verdict: {len(have_subagent_verdict)}", flush=True)
    if args.limit: have_subagent_verdict = have_subagent_verdict[:args.limit]

    lock = threading.Lock()
    done = [0]
    def go(d):
        slug, status = process_stage(d)
        with lock:
            done[0] += 1
            print(f"  [{done[0]:3d}/{len(have_subagent_verdict)}] {slug}: {status}", flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        list(ex.map(go, have_subagent_verdict))

    # Aggregate
    print("\n=== A/B comparison ===")
    print(f"{'slug':<60s}  {'subagent':>10s}  {'qwen':>10s}")
    for d in have_subagent_verdict:
        slug = os.path.basename(d.rstrip("/"))
        sub_status, qwen_status = "?", "?"
        sp = os.path.join(d, "verdict.json")
        qp = os.path.join(d, "verdict_qwen.json")
        if os.path.exists(sp):
            try: sub_status = json.load(open(sp)).get("status", "?")
            except: pass
        if os.path.exists(qp):
            try: qwen_status = json.load(open(qp)).get("status", json.load(open(qp)).get("qwen_error", "?")[:30])
            except: pass
        print(f"  {slug[:60]:<60s}  {sub_status[:10]:>10s}  {qwen_status[:30]:>30s}")


if __name__ == "__main__":
    main()

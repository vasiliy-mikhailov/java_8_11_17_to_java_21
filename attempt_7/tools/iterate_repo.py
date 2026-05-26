"""Per-repo iterative recipe-chain search.

For ONE stage at a time:
  1. Start with the default sequenced-Java chain (lombok_safe_bump -> ... -> java21_transforms)
  2. Run it.
  3. If PASS -> record + exit.
  4. If FAIL -> capture observation (which step blew up + log tail).
     Compact prior-attempt history via Qwen.
     Ask Qwen to propose the NEXT chain (full chain, YAML-of-steps).
  5. Retry. Bounded by --max-attempts (default 10).

Output: attempt_7/per_repo_iter/<slug>/
  trajectory.json   — every attempt's chain + verdict + observation + Qwen proposal
  history.md        — human-readable narrative
  final_chain.yaml  — the chain that finally passed (or last tried)

Usage:
  iterate_repo.py --repo owner/name --sha-from <sha> --sha-to <sha> --jv-from 8 --jv-to 21 [--max-attempts 10]

Or batch:
  iterate_repo.py --sample stages.json   # iterate over a list, one at a time
"""
import os, sys, json, time, copy, argparse, uuid, tempfile, shutil, subprocess
import urllib.request, urllib.error

# Reuse machinery from the sequenced runner
sys.path.insert(0, "/home/vmihaylov/java_8_11_17_to_java_21/attempt_7/tools")
from run_sequenced_java import (
    plan_for, write_recipe_yaml, shallow_fetch, docker_phase,
    WORK, BASE, ATTEMPT7,
)

OUT_DIR = f"{ATTEMPT7}/per_repo_iter"
os.makedirs(OUT_DIR, exist_ok=True)

# Qwen / vLLM config
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
VLLM_URL = ENV.get("VLLM_BASE_URL", "https://inference.mikhailov.tech/v1")
VLLM_KEY = ENV.get("VLLM_API_KEY", "")
VLLM_MODEL = ENV.get("VLLM_MODEL", "qwen3.6-27b-fp8")

COMPAT_MATRIX = open(f"{ATTEMPT7}/COMPAT_MATRIX.md").read()


SYSTEM_PROPOSER = """You drive an iterative search for an OpenRewrite recipe chain that migrates a Java/Maven project from jv_from to jv_to.

Each iteration runs a CHAIN of steps. Each step is:
  {label, jdk, recipes: [...]}
After each step, the runner applies the recipes via OpenRewrite, then runs `mvn compile` under the given JDK. The chain aborts at the first step that fails recipe-apply or build.

Your job: given the CURRENT chain that just failed, the FAILURE LOG, and a COMPACTED HISTORY of prior attempts, propose the NEXT chain to try.

Allowed primitives (full FQN; either a bare string or a mapping with parameters):
  org.openrewrite.maven.UpgradeDependencyVersion (groupId, artifactId, newVersion)
  org.openrewrite.maven.ChangePropertyValue (key, newValue)
  org.openrewrite.maven.AddProperty (key, value)
  org.openrewrite.maven.UpgradeParentVersion (groupId, artifactId, newVersion)
  org.openrewrite.maven.ChangeParentPom (oldGroupId, oldArtifactId, newGroupId, newArtifactId, newVersion)
  org.openrewrite.maven.AddDependency (groupId, artifactId, version, scope?, type?)
  org.openrewrite.maven.RemoveDependency (groupId, artifactId)
  org.openrewrite.maven.UpgradePluginVersion (groupId, artifactId, newVersion)
  org.openrewrite.java.migrate.UpgradeToJava11 / 17 / 21
  org.openrewrite.java.migrate.UpgradeBuildToJava17 / 21
  org.openrewrite.java.migrate.UpgradePluginsForJava17 / 21
  org.openrewrite.java.migrate.Java8toJava11
  org.openrewrite.java.migrate.RemoveIllegalSemicolons
  org.openrewrite.java.migrate.lang.ThreadStopUnsupported
  org.openrewrite.java.migrate.net.URLConstructorToURICreate
  org.openrewrite.java.migrate.util.SequencedCollection
  org.openrewrite.java.migrate.util.UseLocaleOf
  org.openrewrite.java.migrate.DeleteDeprecatedFinalize
  org.openrewrite.java.migrate.RemovedSubjectMethods
  org.openrewrite.staticanalysis.InstanceOfPatternMatch
  org.openrewrite.staticanalysis.ReplaceDeprecatedRuntimeExecMethods
  org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7
  org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_0
  org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_1
  org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2
  org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_3
  org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_4
  org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_5
  org.openrewrite.java.spring.boot3.SpringBoot3BestPractices
  org.openrewrite.java.spring.framework.UpgradeSpringFramework_6_1
  org.openrewrite.java.migrate.jakarta.JakartaEE10
  org.openrewrite.java.migrate.jakarta.JavaxMigrationToJakarta
  org.openrewrite.java.migrate.jakarta.JavaxServletMigrationToJakartaServlet
  org.openrewrite.java.migrate.jakarta.JavaxValidationMigrationToJakartaValidation
  org.openrewrite.java.migrate.jakarta.JavaxXmlBindMigrationToJakartaXmlBind
  org.openrewrite.hibernate.MigrateToHibernate61
  org.openrewrite.hibernate.MigrateToHibernate62
  org.openrewrite.hibernate.MigrateToHibernate66
  org.openrewrite.java.testing.junit5.JUnit4to5Migration
  org.openrewrite.java.testing.mockito.MockitoBestPractices
  org.openrewrite.java.testing.mockito.Mockito1to3Migration
  org.openrewrite.java.testing.mockito.Mockito3to4Migration
  org.openrewrite.java.testing.assertj.JUnitToAssertj
  org.openrewrite.java.migrate.jackson.UpgradeJacksonVersion_2_x
  org.openrewrite.java.migrate.lombok.LombokBestPractices
  org.openrewrite.java.migrate.lang.UseTextBlocks
  org.openrewrite.java.migrate.lang.StringFormatted
  org.openrewrite.java.migrate.lang.var.UseVarKeyword
  org.openrewrite.java.RemoveUnusedImports
  org.openrewrite.java.OrderImports

Mutation strategies you may apply:
  - ADD a property/dependency bump before a build-bump step (most common fix).
  - SWAP a step's recipe for a more specific one.
  - INSERT a new step (e.g., Spring Boot bump) between existing steps.
  - REMOVE a step that's harmful.
  - CHANGE a step's JDK (rare).

Return STRICT JSON with this shape (and nothing else):
{
  "observation": "<one sentence: what broke + suspected root cause>",
  "rationale":   "<one short paragraph: why this mutation should fix it>",
  "next_chain": [
    {"label": "...", "jdk": 11, "recipes": [
       "org.openrewrite.java.migrate.Java8toJava11",
       {"name": "org.openrewrite.maven.ChangePropertyValue", "key": "java.version", "newValue": "11"}
    ]},
    ...
  ]
}

Do NOT include thinking traces or markdown fences. Just the JSON.
"""


def call_qwen(system, user, *, max_tokens=8192, enable_thinking=True, temperature=0.0):
    payload = {
        "model": VLLM_MODEL,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
    }
    req = urllib.request.Request(
        f"{VLLM_URL.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {VLLM_KEY}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode(errors='replace')[:400]}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"
    return data["choices"][0]["message"]["content"], None


def extract_json(text):
    """Pull the first balanced JSON object out of a Qwen response."""
    if text is None: return None
    # strip thinking tags if present
    if "</think>" in text:
        text = text.split("</think>", 1)[1]
    text = text.strip()
    # strip markdown fences
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
    # find first { and matching }
    i = text.find("{")
    if i < 0: return None
    depth = 0
    in_str = False
    esc = False
    for j in range(i, len(text)):
        c = text[j]
        if esc:
            esc = False; continue
        if c == "\\" and in_str:
            esc = True; continue
        if c == '"':
            in_str = not in_str
        elif not in_str:
            if c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try: return json.loads(text[i:j+1])
                    except Exception: return None
    return None


def run_chain(stage, chain, *, log_tail_bytes=8192):
    """Run one chain on a fresh clone of the repo. Returns trajectory dict.

    `chain` is list of (label, jdk, recipes).
    """
    repo = stage["repo"]; sha_from = stage["sha_from"]
    jf = stage.get("jv_from"); jt = stage.get("jv_to")
    slug = f"{repo.replace('/', '_')}__J{jf}toJ{jt}"

    work = tempfile.mkdtemp(prefix="iter_w_", dir=WORK)
    recipes_dir = tempfile.mkdtemp(prefix="iter_r_", dir=WORK)
    logs = tempfile.mkdtemp(prefix="iter_l_", dir=WORK)
    traj = {"chain_in": chain, "started_at": time.time(), "steps": []}
    try:
        if not shallow_fetch(repo, sha_from, work):
            traj["error"] = "checkout_failed"
            return traj
        for label, jdk, recipe_list in chain:
            rfile = os.path.join(recipes_dir, f"{label}.yml")
            write_recipe_yaml(rfile, f"org.example.iter.{slug}.{label}", recipe_list)
            # per-step log_dir so successive build_post calls don't accumulate into one file
            step_logs = tempfile.mkdtemp(prefix=f"iter_l_{label}_", dir=WORK)
            rc_r, log_r = docker_phase(work, recipes_dir, step_logs, "recipe", jdk,
                                       recipe_file=rfile, timeout=1200)
            entry = {"step": label, "jdk": jdk, "recipe_count": len(recipe_list),
                     "recipe_rc": rc_r, "recipe_ok": rc_r == 0}
            if rc_r != 0:
                entry["recipe_log_full"] = log_r
                entry["recipe_log_tail"] = log_r[-log_tail_bytes:]
            else:
                rc_b, log_b = docker_phase(work, recipes_dir, step_logs, "build_post", jdk, timeout=600)
                entry["build_rc"] = rc_b
                entry["build_ok"] = rc_b == 0
                if rc_b != 0:
                    entry["build_log_full"] = log_b
                    entry["build_log_tail"] = log_b[-log_tail_bytes:]
            shutil.rmtree(step_logs, ignore_errors=True)
            traj["steps"].append(entry)
            if not entry["recipe_ok"] or not entry.get("build_ok", True):
                traj["aborted_at"] = label
                break
        traj["finished_at"] = time.time()
        last = traj["steps"][-1] if traj["steps"] else None
        traj["final_status"] = (
            "PASS" if last and last.get("recipe_ok") and last.get("build_ok")
            else "FAIL_at_" + (last.get("step", "?") if last else "no_steps")
        )
    finally:
        for d in (work, recipes_dir, logs):
            shutil.rmtree(d, ignore_errors=True)
    return traj


def _extract_error_context(log, max_bytes=6000):
    """Pull [ERROR] / Exception / Failure lines with surrounding context out of a maven log.

    Strategy: find the first ERROR/exception block, grab ~80 lines around it. If multiple
    blocks, prefer the EARLIEST (root-cause usually), but also include the LAST 30 lines
    so we see the final maven summary.
    """
    if not log: return ""
    lines = log.splitlines()
    # Find indices of interesting lines
    sig_re = ("[ERROR]", "BUILD FAILURE", "java.lang.", "Caused by:", "Compilation failure",
              "at org.openrewrite", "Exception in thread", "FAILED")
    hits = [i for i, ln in enumerate(lines) if any(s in ln for s in sig_re)]
    parts = []
    if hits:
        # earliest cluster: 5 lines before first hit, 60 lines after
        first = hits[0]
        start = max(0, first - 5)
        end = min(len(lines), first + 60)
        parts.append("--- first error cluster ---")
        parts.extend(lines[start:end])
        # final 30 lines (summary / "BUILD FAILURE" header)
        if end < len(lines) - 30:
            parts.append("--- final 30 lines ---")
            parts.extend(lines[-30:])
    else:
        # no signature hits — fall back to plain tail
        parts.append("--- log tail (no [ERROR] markers found) ---")
        parts.extend(lines[-60:])
    out = "\n".join(parts)
    if len(out) > max_bytes:
        out = out[:max_bytes] + "\n... [truncated] ..."
    return out


def extract_observation(traj):
    if "error" in traj: return f"checkout failed for {traj.get('error')}"
    last = traj["steps"][-1] if traj["steps"] else None
    if not last: return "no steps ran"
    log = last.get("recipe_log_full") or last.get("build_log_full") or ""
    ctx = _extract_error_context(log)
    if last.get("recipe_ok") is False:
        return f"step `{last['step']}` (jdk={last['jdk']}): RECIPE APPLY FAILED, rc={last['recipe_rc']}\n{ctx}"
    else:
        return f"step `{last['step']}` (jdk={last['jdk']}): BUILD FAILED post-recipe, rc={last.get('build_rc')}\n{ctx}"


def render_chain_for_qwen(chain):
    out = []
    for label, jdk, recipes in chain:
        rs = []
        for r in recipes:
            if isinstance(r, str): rs.append(r)
            else: rs.append({k: v for k, v in r.items()})
        out.append({"label": label, "jdk": jdk, "recipes": rs})
    return out


def chain_from_qwen(qwen_chain):
    """Convert JSON list-of-step-dicts -> tuples (label, jdk, recipes)."""
    chain = []
    for st in qwen_chain:
        label = st.get("label") or "unnamed"
        jdk = int(st.get("jdk", 21))
        recipes = []
        for r in st.get("recipes", []):
            if isinstance(r, str): recipes.append(r)
            elif isinstance(r, dict): recipes.append(r)
        chain.append((label, jdk, recipes))
    return chain


def compact_history(history_entries):
    """Use Qwen to summarize prior attempts into ~150 words."""
    if not history_entries: return ""
    bullets = []
    for i, h in enumerate(history_entries, 1):
        chain_brief = " -> ".join(st["label"] for st in render_chain_for_qwen(h["chain"]))
        bullets.append(
            f"Attempt {i}: chain = [{chain_brief}]\n"
            f"  verdict: {h['traj'].get('final_status','?')}\n"
            f"  observation: {h['observation'][:600]}\n"
            f"  qwen rationale: {h['qwen_rationale'][:400]}"
        )
    user = (
        "Summarize the prior attempts below into a tight ~150-word recap "
        "for the next planner. Surface: which steps consistently break, what "
        "mutations have been tried already (so the next attempt doesn't repeat), "
        "and the suspected blocker.\n\n"
        + "\n\n".join(bullets)
    )
    text, err = call_qwen("You are a concise technical summarizer.", user,
                          max_tokens=2048, enable_thinking=False, temperature=0.0)
    if err: return f"(compactor failed: {err})"
    # strip thinking artifacts
    if "</think>" in text: text = text.split("</think>", 1)[1]
    return text.strip()


def propose_next_chain(stage, current_chain, observation, history_recap):
    qwen_chain = render_chain_for_qwen(current_chain)
    user = (
        f"Repo: {stage['repo']}\n"
        f"jv_from={stage['jv_from']}  jv_to={stage['jv_to']}\n\n"
        f"=== COMPAT MATRIX ===\n{COMPAT_MATRIX}\n\n"
        f"=== CURRENT CHAIN (just failed) ===\n{json.dumps(qwen_chain, indent=2)}\n\n"
        f"=== FAILURE ===\n{observation}\n\n"
        f"=== PRIOR ATTEMPTS RECAP ===\n{history_recap or '(this is the first attempt)'}\n\n"
        "Propose the NEXT chain. Return STRICT JSON per the system prompt schema."
    )
    text, err = call_qwen(SYSTEM_PROPOSER, user, max_tokens=16384,
                          enable_thinking=True, temperature=0.0)
    if err: return None, f"qwen err: {err}"
    obj = extract_json(text)
    if obj is None:
        # retry without thinking
        text2, err2 = call_qwen(SYSTEM_PROPOSER, user, max_tokens=8192,
                                enable_thinking=False, temperature=0.0)
        if err2: return None, f"qwen err (no-think): {err2}"
        obj = extract_json(text2)
        if obj is None: return None, "unparseable JSON from Qwen"
    return obj, None


def _save_trajectory(out_dir, stage, max_attempts, history_lite, next_chain_dicts):
    """Persist trajectory + the chain Qwen wants tried next (so resume continues)."""
    final = history_lite[-1]["verdict"] if history_lite else "?"
    out = {"stage": stage, "max_attempts": max_attempts, "history": history_lite,
           "next_chain_to_try": next_chain_dicts, "final_verdict": final}
    json.dump(out, open(f"{out_dir}/trajectory.json", "w"), indent=2)
    return out


def _history_to_fakes(history_lite):
    """compact_history wants [{chain, traj, observation, qwen_rationale}].
    Convert the persisted lite form back to that shape."""
    out = []
    for h in history_lite:
        out.append({
            "chain": chain_from_qwen(h["chain"]),
            "traj": {"final_status": h["verdict"]},
            "observation": h.get("observation", ""),
            "qwen_rationale": h.get("qwen_rationale", ""),
        })
    return out


def iterate_one(stage, max_attempts=10):
    """Run iterator on one stage, up to max_attempts TOTAL (resumes from cached state)."""
    slug = f"{stage['repo'].replace('/', '_')}__J{stage['jv_from']}toJ{stage['jv_to']}"
    out_dir = f"{OUT_DIR}/{slug}"
    os.makedirs(out_dir, exist_ok=True)
    tpath = f"{out_dir}/trajectory.json"

    # Resume from cached trajectory if any
    history_lite = []
    chain = None
    if os.path.exists(tpath):
        prev = json.load(open(tpath))
        if prev.get("final_verdict") == "PASS":
            print(f"[{slug}] cached PASS (attempt {len(prev.get('history', []))})", flush=True)
            return prev
        history_lite = prev.get("history", [])
        if len(history_lite) >= max_attempts:
            print(f"[{slug}] cached FAIL {prev.get('final_verdict')} — already at budget {max_attempts}", flush=True)
            return prev
        # restore the chain Qwen proposed at the end of last pass, else replay last chain
        next_dicts = prev.get("next_chain_to_try")
        if next_dicts:
            chain = chain_from_qwen(next_dicts)
        elif history_lite:
            chain = chain_from_qwen(history_lite[-1]["chain"])

    if chain is None:
        chain = plan_for(stage["jv_from"], stage["jv_to"])

    start_attempt = len(history_lite) + 1
    print(f"[{slug}] starting attempt {start_attempt}/{max_attempts} ({len(history_lite)} prior)", flush=True)

    for attempt in range(start_attempt, max_attempts + 1):
        attempt_t0 = time.time()
        chain_brief = " -> ".join(st[0] for st in chain)
        print(f"[{slug}] === attempt {attempt}/{max_attempts} ===\n[{slug}]   chain: {chain_brief}", flush=True)
        traj = run_chain(stage, chain)
        wall_s = round(time.time() - attempt_t0, 1)
        verdict = traj.get("final_status", "?")
        print(f"[{slug}]   verdict: {verdict}  (wall_s={wall_s})", flush=True)

        steps_brief = [{"step": s["step"], "jdk": s["jdk"],
                        "recipe_ok": s.get("recipe_ok"), "build_ok": s.get("build_ok")}
                       for s in traj.get("steps", [])]

        if verdict == "PASS":
            history_lite.append({"attempt": attempt, "chain": render_chain_for_qwen(chain),
                                 "verdict": "PASS", "aborted_at": None,
                                 "wall_s": wall_s, "steps": steps_brief,
                                 "observation": "PASS", "qwen_observation": "",
                                 "qwen_rationale": ""})
            _save_trajectory(out_dir, stage, max_attempts, history_lite, None)
            break

        obs = extract_observation(traj)
        print(f"[{slug}]   observation: {obs[:200]}", flush=True)
        recap = compact_history(_history_to_fakes(history_lite)) if history_lite else ""
        proposal, perr = propose_next_chain(stage, chain, obs, recap)
        next_chain_dicts = None
        rationale = ""
        qwen_obs = ""
        next_chain = None
        if proposal is None:
            print(f"[{slug}]   qwen proposer failed: {perr}", flush=True)
            rationale = f"proposer error: {perr}"
        else:
            next_chain_dicts = proposal.get("next_chain", [])
            next_chain = chain_from_qwen(next_chain_dicts)
            rationale = proposal.get("rationale", "")
            qwen_obs = proposal.get("observation", "")
            print(f"[{slug}]   qwen obs: {qwen_obs[:160]}\n[{slug}]   qwen rationale: {rationale[:160]}", flush=True)
            next_brief = " -> ".join(st[0] for st in next_chain)
            print(f"[{slug}]   next chain: {next_brief}", flush=True)

        history_lite.append({"attempt": attempt, "chain": render_chain_for_qwen(chain),
                             "verdict": verdict, "aborted_at": traj.get("aborted_at"),
                             "wall_s": wall_s, "steps": steps_brief,
                             "observation": obs[:8192],
                             "qwen_observation": qwen_obs,
                             "qwen_rationale": rationale[:2048]})
        _save_trajectory(out_dir, stage, max_attempts, history_lite, next_chain_dicts)

        if not proposal or not next_chain:
            print(f"[{slug}]   empty proposal — bailing", flush=True)
            break
        if render_chain_for_qwen(next_chain) == render_chain_for_qwen(chain):
            print(f"[{slug}]   proposal == current chain — bailing", flush=True)
            break
        chain = next_chain

    out = json.load(open(tpath))
    print(f"[{slug}] FINAL: {out['final_verdict']}  (attempts: {len(out['history'])})", flush=True)
    return out


def main():
    from concurrent.futures import ThreadPoolExecutor
    import threading
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--repo")
    g.add_argument("--sample", help="JSON list of stages")
    ap.add_argument("--sha-from")
    ap.add_argument("--sha-to", default="")
    ap.add_argument("--jv-from", type=int)
    ap.add_argument("--jv-to", type=int, default=21)
    ap.add_argument("--max-attempts", type=int, default=10)
    ap.add_argument("--workers", type=int, default=1)
    args = ap.parse_args()

    if args.repo:
        assert args.sha_from and args.jv_from is not None, "need --sha-from and --jv-from with --repo"
        stages = [{"repo": args.repo, "sha_from": args.sha_from, "sha_to": args.sha_to,
                   "jv_from": args.jv_from, "jv_to": args.jv_to}]
    else:
        stages = json.load(open(args.sample))
    for s in stages: s.setdefault("jv_to", 21)

    print(f"== iterating {len(stages)} stages, max_attempts={args.max_attempts}, workers={args.workers} ==", flush=True)
    done = [0]; lock = threading.Lock()
    def go(s):
        try: r = iterate_one(s, max_attempts=args.max_attempts)
        except Exception as e:
            r = {"final_verdict": f"EXC:{type(e).__name__}:{e}"}
            print(f"[{s['repo']}] EXCEPTION: {type(e).__name__}: {e}", flush=True)
        with lock:
            done[0] += 1
            print(f"== progress {done[0]}/{len(stages)}: {s['repo']} -> {r.get('final_verdict','?')} ==", flush=True)
        return r

    if args.workers == 1:
        for s in stages: go(s)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            list(ex.map(go, stages))
    print("== done ==", flush=True)


if __name__ == "__main__":
    main()

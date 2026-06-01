"""ff #1 iter-1+ composer: reads item 3's intent_samples + item 4's recipe_samples,
computes per-stage only_human breaking sets, aggregates per jv_to, asks Qwen to suggest
an OpenRewrite recipe addition per top missed-intent cluster, emits new recipe.yaml.

Idempotent — running it doesn't change recipe.yaml if no additions would improve coverage.
"""
import os, json, sys, argparse, collections, hashlib, urllib.request, re

HERE = "/home/vmihaylov/java_8_11_17_to_java_21"
ATTEMPT = f"{HERE}/attempt_6"
INTENT_SAMPLES = f"{ATTEMPT}/intent_samples"
RECIPE_SAMPLES = f"{ATTEMPT}/recipe_samples"
RECIPE_YAML = f"{ATTEMPT}/recipe.yaml"
PROPOSER_URL = "http://localhost:8000/v1/chat/completions"
PROPOSER_KEY = "sk-ef2926520a83b7f6efac7f4dc5b049842b4b2baebfdc18b69b76220f29fdf272"


def load_breaking(base, slug):
    p = os.path.join(base, slug, "breaking.json")
    if not os.path.exists(p): return None
    try: return json.load(open(p)).get("by_file", {}) or {}
    except: return None


def stage_jv(slug):
    """Parse '<repo_safe>__J<from>toJ<to>' → (jv_from, jv_to). Returns (None, None) if unparseable."""
    m = re.search(r"__J(\d+)toJ(\d+)$", slug)
    if not m: return None, None
    return int(m.group(1)), int(m.group(2))


def all_atoms(by_file):
    for f, xs in (by_file or {}).items():
        for it in xs:
            yield f, it


def kind_signature(atom):
    """Normalised kind label for set-based matching. Strip digits and short suffixes."""
    k = (atom.get("kind") or "").lower()
    k = re.sub(r"[_\d]+$", "", k)
    return k or "?"


def per_stage_only_human(slug):
    """Return list of human breaking atoms that have no recipe counterpart (same kind_signature)."""
    h = load_breaking(INTENT_SAMPLES, slug)
    r = load_breaking(RECIPE_SAMPLES, slug)
    if h is None or r is None: return None  # incomplete pair
    human_atoms = list(all_atoms(h))
    recipe_atoms = list(all_atoms(r))
    recipe_sigs = {kind_signature(a) for _, a in recipe_atoms}
    return [a for _, a in human_atoms if kind_signature(a) not in recipe_sigs]


def aggregate_missed():
    """For each jv_to, collect missed human atoms and count by kind_signature."""
    per_jv = collections.defaultdict(list)
    n_stages_paired = collections.Counter()
    for slug in sorted(os.listdir(INTENT_SAMPLES)):
        if not os.path.isdir(os.path.join(INTENT_SAMPLES, slug)): continue
        jv_from, jv_to = stage_jv(slug)
        if jv_to is None: continue
        missed = per_stage_only_human(slug)
        if missed is None: continue  # recipe_samples not yet computed
        n_stages_paired[jv_to] += 1
        per_jv[jv_to].extend(missed)
    return per_jv, n_stages_paired


def cluster_by_signature(atoms, top_n=10):
    """Group atoms by kind_signature, return [(sig, count, examples)] sorted by count desc."""
    grouped = collections.defaultdict(list)
    for a in atoms:
        grouped[kind_signature(a)].append(a)
    out = []
    for sig, items in grouped.items():
        examples = sorted(items, key=lambda x: -len((x.get("general_idea") or "")))[:3]
        out.append((sig, len(items), examples))
    out.sort(key=lambda x: -x[1])
    return out[:top_n]


def ask_qwen_for_recipe(jv_to, cluster_sig, examples):
    """Ask Qwen to suggest one OpenRewrite recipe class name addressing the cluster."""
    listing = "\n".join(
        f"- kind={a.get('kind')}\n  why_exists={(a.get('why_exists') or '')[:200]}\n  before={(a.get('before') or '')[:140]}\n  after={(a.get('after') or '')[:140]}"
        for a in examples
    )
    user = (
        f"The current OpenRewrite migration to Java {jv_to} fails to make the following breaking changes "
        f"(human committed these, but the recipe did not). Suggest the SINGLE most-fitting OpenRewrite "
        f"recipe class name (from rewrite-migrate-java:3.16.0, rewrite-spring:6.x, rewrite-testing-frameworks:3.x, "
        f"or rewrite-hibernate:2.x) whose published behaviour would make these changes when added to the "
        f"composition. Reply ONLY with the fully-qualified class name (e.g. "
        f"org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_2). If no known recipe addresses this cluster, "
        f"reply NONE.\n\n"
        f"Cluster signature: {cluster_sig}\nExamples ({len(examples)} of {len(examples)}):\n{listing}"
    )
    body = {
        "model": "qwen3.6-27b-fp8",
        "messages": [
            {"role": "system", "content": "You are an expert in OpenRewrite recipe catalog. Reply with one class name or NONE. No prose."},
            {"role": "user", "content": user},
        ],
        "temperature": 0.0,
        "max_tokens": 200,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        PROPOSER_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {PROPOSER_KEY}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
        content = resp["choices"][0]["message"].get("content", "").strip()
    except Exception as e:
        return f"ERROR:{e}"
    # Strip backticks, quotes, trailing punctuation
    content = content.strip("`'\" .,\n")
    return content


def load_recipe_yaml():
    if not os.path.exists(RECIPE_YAML): return {}
    import yaml
    with open(RECIPE_YAML) as f:
        d = yaml.safe_load(f) or {}
    return {int(k): list(v or []) for k, v in d.items()}


def emit_recipe(composition, path):
    lines = ["# Emitted by ff #1 composer (iter-1+).", "# Format: per-jv_to list of OpenRewrite recipe class names.", ""]
    for jv_to in sorted(composition):
        lines.append(f"{jv_to}:")
        for r in composition[jv_to]:
            lines.append(f"  - {r}")
    open(path, "w").write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-clusters", type=int, default=5, help="Top missed-intent clusters to analyse per jv_to")
    parser.add_argument("--dry-run", action="store_true", help="Analyse only; do not modify recipe.yaml")
    args = parser.parse_args()

    print(f"reading intent_samples from {INTENT_SAMPLES}")
    print(f"reading recipe_samples from {RECIPE_SAMPLES}")
    per_jv, n_paired = aggregate_missed()
    if not per_jv:
        print("no paired (intent_samples ∩ recipe_samples) stages found yet. wait for ff #4 to populate recipe_samples.")
        return

    current = load_recipe_yaml()
    print(f"current recipe.yaml: {current}")

    suggestions = {}
    for jv_to in sorted(per_jv):
        missed = per_jv[jv_to]
        print(f"\n=== jv_to=J{jv_to} ({n_paired[jv_to]} paired stages, {len(missed)} only_human breaking atoms) ===")
        clusters = cluster_by_signature(missed, top_n=args.top_clusters)
        for sig, count, examples in clusters:
            print(f"  [{count:4d}x] {sig}  e.g.: {(examples[0].get('general_idea') or '')[:120]}")

        # Ask Qwen for the top cluster
        if not clusters:
            continue
        top_sig, top_count, top_examples = clusters[0]
        already = set(current.get(jv_to, []))
        suggestion = ask_qwen_for_recipe(jv_to, top_sig, top_examples)
        print(f"  ↳ Qwen suggests for top cluster: {suggestion}")
        if suggestion and suggestion != "NONE" and not suggestion.startswith("ERROR") and suggestion not in already:
            suggestions[jv_to] = suggestion

    if not suggestions:
        print("\nno new additions proposed.")
        return

    print(f"\nproposed additions: {suggestions}")
    if args.dry_run:
        print("(dry-run; not modifying recipe.yaml)")
        return

    new_composition = dict(current)
    for jv_to, recipe_name in suggestions.items():
        new_composition.setdefault(jv_to, list(current.get(jv_to, []))).append(recipe_name)
    emit_recipe(new_composition, RECIPE_YAML)
    print(f"wrote {RECIPE_YAML}")
    print(open(RECIPE_YAML).read())


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""D10 outer-level post-run persistence.

Snapshots prompt + recipe catalog, persists OH dialogue + bump diff,
writes structured trajectory.json + appends feedback.jsonl.

Usage:
  d10_outer_persist.py <slug> <workdir> <oh_log_path> <jv_from> <jv_to> [<pre_counts_json>]

If <pre_counts_json> is omitted, pre_test_counts stays null (caller must capture
baseline separately for a real PASS verdict). Otherwise expects a JSON file with
{tests, failures, errors, skipped, passing: ["class::method", ...]}.
"""
import os, sys, json, hashlib, shutil, subprocess, time, glob, re
import xml.etree.ElementTree as ET

ATTEMPT_DIR = '/home/vmihaylov/java_8_11_17_to_java_21/current_attempt'
PROMPT_PATH = f'{ATTEMPT_DIR}/prompt.md'
RECIPE_JAR = '/home/vmihaylov/.m2-fitness/repository/com/claude/recipes/bump-java-version-recipes/1.0.0/bump-java-version-recipes-1.0.0.jar'
FEEDBACK_JSONL = f'{ATTEMPT_DIR}/feedback.jsonl'

def sha12(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f: h.update(f.read())
    return h.hexdigest()[:12]

def snapshot(src, dest_dir, sha):
    os.makedirs(dest_dir, exist_ok=True)
    ext = os.path.splitext(src)[1]
    dest = f'{dest_dir}/{sha}{ext}'
    if not os.path.exists(dest): shutil.copy2(src, dest)
    return dest

def surefire_counts(workdir):
    t=f=e=sk=0; passing=[]
    for x in glob.glob(f'{workdir}/**/target/surefire-reports/TEST-*.xml', recursive=True):
        try:
            r = ET.parse(x).getroot()
            t+=int(r.get('tests',0)); f+=int(r.get('failures',0))
            e+=int(r.get('errors',0)); sk+=int(r.get('skipped',0))
            for tc in r.findall('testcase'):
                if tc.find('failure') is None and tc.find('error') is None:
                    passing.append(tc.get('classname','?') + '::' + tc.get('name','?'))
        except: pass
    return {'tests':t,'failures':f,'errors':e,'skipped':sk,'passing':passing}

def pom_java_version(workdir):
    # Scan ALL pom.xml in the tree (nested-project repos like foo/junit/pom.xml + multi-module
    # aggregators), not just the workdir root. MAX java level across the four knobs. None only if
    # no pom declares a level.
    import glob
    pats = [r'<java\.version>([^<]+)</java\.version>',
            r'<maven\.compiler\.release>([^<]+)</maven\.compiler\.release>',
            r'<maven\.compiler\.source>([^<]+)</maven\.compiler\.source>',
            r'<maven\.compiler\.target>([^<]+)</maven\.compiler\.target>']
    pats = pats + [r"<release> *([0-9]+) *</release>", r"<source> *([0-9]+) *</source>", r"<target> *([0-9]+) *</target>"]
    vals = []
    for pom in glob.glob(f'{workdir}/**/pom.xml', recursive=True):
        if '/.git/' in pom: continue
        try: txt = open(pom).read()
        except Exception: continue
        for p in pats:
            for m in re.finditer(p, txt):
                try:
                    _v=int(m.group(1).strip())
                    if 7<=_v<=30: vals.append(_v)
                except Exception: pass
    return str(max(vals)) if vals else None

def git_diff(workdir):
    # Try HEAD~1..HEAD first; if only 1 commit, fall back to git diff HEAD (working tree vs HEAD)
    has_two = subprocess.run(['git','rev-parse','HEAD~1'], cwd=workdir, capture_output=True).returncode == 0
    if has_two:
        return subprocess.run(['git','diff','HEAD~1..HEAD'], cwd=workdir, capture_output=True, text=True).stdout
    return subprocess.run(['git','diff','HEAD'], cwd=workdir, capture_output=True, text=True).stdout

def detect_bail_label(oh_log_path):
    # Scan last 100 lines of the dialogue log for a line of the canonical form BAIL:<LABEL>
    if not os.path.exists(oh_log_path): return None
    try:
        lines = open(oh_log_path).read().splitlines()
    except: return None
    for ln in reversed(lines[-100:]):
        s = ln.strip()
        m = re.match(r'^BAIL:([A-Z][A-Z0-9_]+)$', s)
        if m: return 'BAIL:' + m.group(1)
    return None

def compute_verdict(pom_v, jv_to, pre, post, oh_log_path=None):
    # If executor emitted a canonical BAIL:<LABEL> line, that is the terminal outcome
    bail = detect_bail_label(oh_log_path) if oh_log_path else None
    if bail:
        return bail
    if pom_v is None or int(pom_v) < int(jv_to):
        return 'BAIL:pom_not_bumped'
    if pre is None:
        if post['failures'] + post['errors'] == 0:
            return 'PASS_NOBASELINE'
        return 'FAIL'
    baseline_pass = set(pre['passing'])
    post_pass = set(post['passing'])
    if baseline_pass.issubset(post_pass):
        return 'PASS'
    regressed = sorted(baseline_pass - post_pass)
    return 'FAIL:regressed_' + str(len(regressed))

def main():
    if len(sys.argv) < 6:
        print('usage: d10_outer_persist.py <slug> <workdir> <oh_log> <jv_from> <jv_to> [<pre_counts.json>]', file=sys.stderr)
        sys.exit(2)
    slug, workdir, oh_log = sys.argv[1], sys.argv[2], sys.argv[3]
    jv_from, jv_to = int(sys.argv[4]), int(sys.argv[5])
    pre = None
    if len(sys.argv) > 6 and os.path.exists(sys.argv[6]):
        pre = json.load(open(sys.argv[6]))

    prompt_sha = sha12(PROMPT_PATH)
    catalog_sha = sha12(RECIPE_JAR)
    snapshot(PROMPT_PATH, f'{ATTEMPT_DIR}/prompt_snapshots', prompt_sha)
    snapshot(RECIPE_JAR, f'{ATTEMPT_DIR}/recipe_snapshots', catalog_sha)

    stage_dir = f'{ATTEMPT_DIR}/per_repo_iter/{slug}'
    os.makedirs(stage_dir, exist_ok=True)

    if os.path.exists(oh_log):
        if os.path.abspath(oh_log) != os.path.abspath(f"{stage_dir}/oh_dialogue.log"): shutil.copy2(oh_log, f"{stage_dir}/oh_dialogue.log")

    diff = git_diff(workdir)
    with open(f'{stage_dir}/bump.diff','w') as f: f.write(diff)

    post = surefire_counts(workdir)
    pom_v = pom_java_version(workdir)
    git_log = subprocess.run(['git','log','--oneline'], cwd=workdir, capture_output=True, text=True).stdout

    wall_seconds, events = None, None
    if os.path.exists(oh_log):
        for line in open(oh_log):
            m = re.search(r'DONE.*wall=([\d.]+)s\s+events=(\d+)', line)
            if m: wall_seconds = float(m.group(1)); events = int(m.group(2)); break

    verdict = compute_verdict(pom_v, jv_to, pre, post, oh_log)

    trajectory = {
        'stage': slug,
        'workdir': workdir,
        'agent_runtime': 'openhands',
        'backend_model': 'openai/qwen-3.6-27b-fp8',
        'prompt_sha': prompt_sha, 'recipe_catalog_sha': catalog_sha,
        'jv_from': jv_from, 'jv_to': jv_to,
        'verdict': verdict,
        'wall_seconds': wall_seconds, 'events': events,
        'pre_test_counts': {k:v for k,v in pre.items() if k != 'passing'} if pre else None,
        'pre_test_passing_count': len(pre['passing']) if pre else None,
        'post_test_counts': {k:v for k,v in post.items() if k != 'passing'},
        'post_test_passing_count': len(post['passing']),
        'post_test_passing_sample': post['passing'][:10],
        'regressed_tests_sample': sorted(set((pre['passing'] if pre else [])) - set(post['passing']))[:10] if pre else None,
        'pom_java_version_post': pom_v,
        'git_log_oneline': git_log.strip().split('\n'),
        'bump_diff_path': f'{stage_dir}/bump.diff',
        'bump_diff_lines': len(diff.splitlines()),
        'oh_dialogue_path': f'{stage_dir}/oh_dialogue.log',
    }
    with open(f'{stage_dir}/trajectory.json','w') as f: json.dump(trajectory, f, indent=2)

    fb_line = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'stage': slug, 'level': 'outer',
        'prompt_sha': prompt_sha, 'recipe_catalog_sha': catalog_sha,
        'outcome': verdict,
        'step_failed': None if verdict.startswith('PASS') else 'see trajectory',
        'error_text': None if verdict.startswith('PASS') else 'see trajectory',
        'agent_trace_excerpt': 'see trajectory.json',
        'what_tried': 'executed prompt verbatim via OH+Qwen',
        'why_failed': None if verdict.startswith('PASS') else verdict,
        'wall_seconds': wall_seconds, 'events': events,
        'trajectory_path': f'{stage_dir}/trajectory.json',
    }
    with open(FEEDBACK_JSONL,'a') as f: f.write(json.dumps(fb_line)+'\n')

    print(f'verdict: {verdict}')
    print(f'snapshots: prompt={prompt_sha} recipe={catalog_sha}')
    print(f'trajectory: {stage_dir}/trajectory.json')
    print(f'dialogue:   {stage_dir}/oh_dialogue.log')
    print(f'diff:       {stage_dir}/bump.diff ({trajectory["bump_diff_lines"]} lines)')

if __name__ == '__main__': main()

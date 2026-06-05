#!/usr/bin/env python3
"""Re-classify existing per_repo_iter trajectories with the patched pom_java_version logic.
Uses bump.diff to detect post-bump pom state (look for + lines with maven.compiler.* or java.version).
Rewrites feedback.jsonl from scratch (one outer entry per stage).
"""
import os, json, re, time

A = '/home/vmihaylov/java_8_11_17_to_java_21/current_attempt'

def max_pom_version_from_diff(diff_text):
    # Look for added (+) lines with java.version or maven.compiler.{release,source,target}
    pats = [
        r'<java\.version>([^<]+)</java\.version>',
        r'<maven\.compiler\.release>([^<]+)</maven\.compiler\.release>',
        r'<maven\.compiler\.source>([^<]+)</maven\.compiler\.source>',
        r'<maven\.compiler\.target>([^<]+)</maven\.compiler\.target>',
        r'<release>([^<]+)</release>',
        r'<source>([^<]+)</source>',
        r'<target>([^<]+)</target>',
    ]
    vals = []
    for ln in diff_text.split('\n'):
        if not ln.startswith('+'): continue
        for p in pats:
            for m in re.finditer(p, ln):
                v = m.group(1).strip()
                try: vals.append(int(v))
                except: pass
    return max(vals) if vals else None

def detect_bail_in_log(log_path):
    if not os.path.exists(log_path): return None
    try:
        lines = open(log_path).read().splitlines()
    except: return None
    for ln in reversed(lines[-100:]):
        m = re.match(r'^BAIL:([A-Z][A-Z0-9_]+)$', ln.strip())
        if m: return 'BAIL:' + m.group(1)
    return None

reclassified = []
flipped = 0
for slug in sorted(os.listdir(f'{A}/per_repo_iter')):
    td = f'{A}/per_repo_iter/{slug}'
    tj = f'{td}/trajectory.json'
    diff = f'{td}/bump.diff'
    dialog = f'{td}/oh_dialogue.log'
    if not os.path.exists(tj): continue
    t = json.load(open(tj))
    old_verdict = t.get('verdict', 'unknown')
    
    # First check: bail label in dialog wins
    bail = detect_bail_in_log(dialog)
    
    new_verdict = old_verdict
    if bail:
        new_verdict = bail
    elif os.path.exists(diff):
        diff_text = open(diff).read()
        pom_max = max_pom_version_from_diff(diff_text)
        jv_to = t.get('jv_to', 21)
        # If diff shows pom bumped to jv_to (in any of the 7 properties), and post_test counts ok, it's PASS
        if pom_max == jv_to:
            post = t.get('post_test_counts', {})
            pre_passing = t.get('pre_test_passing_count', 0) or 0
            post_passing = t.get('post_test_passing_count', 0) or 0
            if pre_passing == 0:
                # Empty BASELINE_PASS — compile-only PASS
                new_verdict = 'PASS_NOBASELINE'
            elif post_passing >= pre_passing and (post.get('failures', 0) + post.get('errors', 0)) == 0:
                new_verdict = 'PASS'
            elif old_verdict == 'BAIL:pom_not_bumped':
                # pom was bumped but tests regressed; reclassify as FAIL
                regressed = pre_passing - post_passing
                new_verdict = f'FAIL:regressed_{regressed}'
    
    if new_verdict != old_verdict:
        flipped += 1
    t['verdict'] = new_verdict
    t['verdict_v1_was'] = old_verdict if new_verdict != old_verdict else None
    json.dump(t, open(tj, 'w'), indent=2)
    reclassified.append((slug, old_verdict, new_verdict, t.get('prompt_sha', ''), t.get('recipe_catalog_sha', '')))

# Rewrite feedback.jsonl from scratch
with open(f'{A}/feedback.jsonl', 'w') as f:
    ts = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    for slug, _, new, psha, csha in reclassified:
        entry = {
            'ts': ts, 'stage': slug, 'level': 'outer',
            'prompt_sha': psha, 'recipe_catalog_sha': csha,
            'outcome': new,
            'step_failed': None if new.startswith('PASS') else 'see trajectory',
            'error_text': None if new.startswith('PASS') else 'see trajectory',
            'agent_trace_excerpt': 'reclassified iter2',
            'what_tried': 'reclassified from existing trajectory with patched wrapper',
            'why_failed': None if new.startswith('PASS') else new,
            'trajectory_path': f'{A}/per_repo_iter/{slug}/trajectory.json',
        }
        f.write(json.dumps(entry) + '\n')

print(f'reclassified {len(reclassified)} trajectories; {flipped} verdict flipped')
print()
print('flipped stages:')
for slug, old, new, _, _ in reclassified:
    if old != new:
        print(f'  {slug[:50]:50s}  {old:30s} → {new}')

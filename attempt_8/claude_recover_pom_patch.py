'''Variant of claude_recover.py: shallow-fetches stage, applies a raw pom.xml patch FIRST,
then invokes run_chain on the patched tree. Tests whether the 'pom_patch' harness extension
would unlock JAXB-cluster cases.'''
import os, sys, json, argparse, time, tempfile, shutil, re

sys.path.insert(0, '/home/vmihaylov/java_8_11_17_to_java_21/attempt_7/tools')
from run_sequenced_java import shallow_fetch, docker_phase, write_recipe_yaml, WORK
from iterate_repo import run_chain
from test_conservation import parse_surefire_dir, check_test_conservation, clear_surefire

# Monkey-patch run_chain to accept pre-checkout-out work_dir
import iterate_repo as ir

def run_chain_on_existing_tree(stage, chain, work_dir, test_conservation=False, log_tail_bytes=8192):
    '''Like run_chain but skips shallow_fetch (work_dir already populated).'''
    repo = stage['repo']
    jf = stage.get('jv_from'); jt = stage.get('jv_to')
    slug = f"{repo.replace('/', '_')}__J{jf}toJ{jt}"
    recipes_dir = tempfile.mkdtemp(prefix='iter_r_', dir=WORK)
    logs = tempfile.mkdtemp(prefix='iter_l_', dir=WORK)
    traj = {'stage': stage, 'chain_in': chain, 'started_at': time.time(), 'steps': []}
    try:
        pre_passed = set(); pre_failed = set()
        if test_conservation:
            tp_logs = tempfile.mkdtemp(prefix='iter_tcpre_', dir=WORK)
            clear_surefire(work_dir)
            rc_tp, log_tp = docker_phase(work_dir, recipes_dir, tp_logs, 'test_pre', jf, timeout=900)
            pre_passed, pre_failed = parse_surefire_dir(work_dir)
            traj['test_pre'] = {'rc': rc_tp, 'passed': len(pre_passed), 'failed': len(pre_failed)}
            shutil.rmtree(tp_logs, ignore_errors=True)
        for label, jdk, recipe_list in chain:
            rfile = os.path.join(recipes_dir, f'{label}.yml')
            write_recipe_yaml(rfile, f'org.example.iter.{slug}.{label}', recipe_list)
            step_logs = tempfile.mkdtemp(prefix=f'iter_l_{label}_', dir=WORK)
            rc_r, log_r = docker_phase(work_dir, recipes_dir, step_logs, 'recipe', jdk,
                                       recipe_file=rfile, timeout=1200)
            entry = {'step': label, 'jdk': jdk, 'recipe_count': len(recipe_list),
                     'recipe_rc': rc_r, 'recipe_ok': rc_r == 0}
            if rc_r != 0:
                entry['recipe_log_tail'] = log_r[-log_tail_bytes:]
            else:
                rc_b, log_b = docker_phase(work_dir, recipes_dir, step_logs, 'build_post', jdk, timeout=600)
                entry['build_rc'] = rc_b
                entry['build_ok'] = rc_b == 0
                if rc_b != 0:
                    entry['build_log_tail'] = log_b[-log_tail_bytes:]
            shutil.rmtree(step_logs, ignore_errors=True)
            traj['steps'].append(entry)
            if not entry['recipe_ok'] or not entry.get('build_ok', True):
                traj['aborted_at'] = label
                break
        compile_pass = bool(traj['steps']) and traj['steps'][-1].get('recipe_ok') and traj['steps'][-1].get('build_ok')
        if test_conservation and compile_pass:
            tp_logs = tempfile.mkdtemp(prefix='iter_tcpost_', dir=WORK)
            clear_surefire(work_dir)
            rc_tp, log_tp = docker_phase(work_dir, recipes_dir, tp_logs, 'test_post', jt, timeout=900)
            post_passed, post_failed = parse_surefire_dir(work_dir)
            traj['test_post'] = {'rc': rc_tp, 'passed': len(post_passed), 'failed': len(post_failed)}
            shutil.rmtree(tp_logs, ignore_errors=True)
            if not pre_passed:
                traj['final_status'] = 'PASS'; traj['test_conservation'] = 'skipped_empty_pre_pass'
            else:
                ok, regressed = check_test_conservation(pre_passed, post_passed)
                traj['final_status'] = 'PASS' if ok else 'FAIL_at_test_conservation'
                traj['test_conservation'] = 'OK' if ok else 'REGRESSED'
                if not ok:
                    traj['regressed_count'] = len(regressed)
                    traj['regressed_tests'] = [f'{c}.{n}' for c, n in regressed[:50]]
        elif compile_pass:
            traj['final_status'] = 'PASS'
        else:
            last = traj['steps'][-1]
            traj['final_status'] = 'FAIL_at_' + last.get('step', '?')
    finally:
        for d in (recipes_dir, logs): shutil.rmtree(d, ignore_errors=True)
    return traj


def inject_deps_into_pom(pom_path, deps):
    '''Inject <dependency> elements into pom.xml's first <dependencies> block.
    deps: list of dicts with groupId/artifactId/version.'''
    text = open(pom_path).read()
    # Build the snippet
    snippets = []
    for d in deps:
        snippets.append(
            f"        <dependency>\n"
            f"            <groupId>{d['groupId']}</groupId>\n"
            f"            <artifactId>{d['artifactId']}</artifactId>\n"
            f"            <version>{d['version']}</version>\n"
            f"        </dependency>"
        )
    inject = '\n' + '\n'.join(snippets) + '\n'
    # Find the FIRST opening <dependencies> (not <dependencyManagement>)
    m = re.search(r'<dependencies>\s*\n', text)
    if not m: raise RuntimeError('no <dependencies> block found in pom')
    new = text[:m.end()] + inject + text[m.end():]
    open(pom_path, 'w').write(new)
    print(f'   injected {len(deps)} deps into {pom_path}', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage-json', required=True)
    ap.add_argument('--chain-json', required=True)
    ap.add_argument('--pom-deps-json', required=True, help='JSON list of {groupId,artifactId,version}')
    ap.add_argument('--out', required=True)
    ap.add_argument('--test-conservation', action='store_true')
    args = ap.parse_args()
    stage = json.loads(args.stage_json)
    chain = [tuple(item) for item in json.loads(args.chain_json)]
    deps = json.loads(args.pom_deps_json)
    work = tempfile.mkdtemp(prefix='claude_recover_', dir=WORK)
    try:
        print(f'== checking out {stage["repo"]} @ {stage["sha_from"][:8]} ==', flush=True)
        if not shallow_fetch(stage['repo'], stage['sha_from'], work):
            raise RuntimeError('shallow_fetch failed')
        # find primary pom
        pom = os.path.join(work, 'pom.xml')
        if not os.path.isfile(pom):
            raise RuntimeError(f'no pom.xml at {pom}')
        inject_deps_into_pom(pom, deps)
        print(f'== running chain on patched tree ==', flush=True)
        t0 = time.time()
        traj = run_chain_on_existing_tree(stage, chain, work,
                                          test_conservation=args.test_conservation)
        print(f'== done in {time.time()-t0:.0f}s: final_status={traj.get("final_status")} ==', flush=True)
        for s in traj.get('steps', []):
            print(f'   step={s["step"]:30s} rc_recipe={s.get("recipe_rc")} rc_build={s.get("build_rc")}', flush=True)
        json.dump(traj, open(args.out, 'w'), indent=2, default=str)
        print(f'   trajectory saved to {args.out}', flush=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()

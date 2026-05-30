'''v2: Use lxml to inject deps into the TOP-LEVEL <dependencies>, not the one inside dependencyManagement.'''
import os, sys, json, argparse, time, tempfile, shutil
from lxml import etree

sys.path.insert(0, '/home/vmihaylov/java_8_11_17_to_java_21/attempt_7/tools')
from run_sequenced_java import shallow_fetch, docker_phase, write_recipe_yaml, WORK

# reuse run_chain_on_existing_tree from v1
sys.path.insert(0, '/home/vmihaylov/java_8_11_17_to_java_21/attempt_8')
from claude_recover_pom_patch import run_chain_on_existing_tree


def inject_deps_lxml(pom_path, deps):
    parser = etree.XMLParser(remove_blank_text=False, recover=True)
    tree = etree.parse(pom_path, parser)
    root = tree.getroot()
    ns = root.nsmap.get(None)
    ns_p = f'{{{ns}}}' if ns else ''
    # Find top-level <dependencies> — direct child of root
    top_deps = None
    for child in root:
        if child.tag == f'{ns_p}dependencies':
            top_deps = child; break
    if top_deps is None:
        # Create one
        top_deps = etree.SubElement(root, f'{ns_p}dependencies')
        top_deps.tail = '\n'
    for d in deps:
        de = etree.SubElement(top_deps, f'{ns_p}dependency')
        gid = etree.SubElement(de, f'{ns_p}groupId'); gid.text = d['groupId']
        aid = etree.SubElement(de, f'{ns_p}artifactId'); aid.text = d['artifactId']
        ver = etree.SubElement(de, f'{ns_p}version'); ver.text = d['version']
        de.tail = '\n        '
    tree.write(pom_path, xml_declaration=True, encoding='UTF-8', pretty_print=False)
    print(f'   lxml-injected {len(deps)} deps into top-level <dependencies>', flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage-json', required=True)
    ap.add_argument('--chain-json', required=True)
    ap.add_argument('--pom-deps-json', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--test-conservation', action='store_true')
    args = ap.parse_args()
    stage = json.loads(args.stage_json)
    chain = [tuple(it) for it in json.loads(args.chain_json)]
    deps = json.loads(args.pom_deps_json)
    work = tempfile.mkdtemp(prefix='claude_recover_', dir=WORK)
    try:
        print(f'== checkout {stage["repo"]} @ {stage["sha_from"][:8]} ==', flush=True)
        if not shallow_fetch(stage['repo'], stage['sha_from'], work):
            raise RuntimeError('shallow_fetch failed')
        inject_deps_lxml(os.path.join(work, 'pom.xml'), deps)
        # verify injection
        with open(os.path.join(work, 'pom.xml')) as f:
            content = f.read()
        for d in deps:
            assert d['artifactId'] in content, f"{d['artifactId']} missing from patched pom"
        print(f'   verified all {len(deps)} artifactIds present in pom.xml', flush=True)
        print('== running chain ==', flush=True)
        t0 = time.time()
        traj = run_chain_on_existing_tree(stage, chain, work,
                                          test_conservation=args.test_conservation)
        print(f'== done in {time.time()-t0:.0f}s: final_status={traj.get("final_status")} ==', flush=True)
        for s in traj.get('steps', []):
            print(f'   step={s["step"]:30s} rc_recipe={s.get("recipe_rc")} rc_build={s.get("build_rc")}', flush=True)
        json.dump(traj, open(args.out, 'w'), indent=2, default=str)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == '__main__':
    main()

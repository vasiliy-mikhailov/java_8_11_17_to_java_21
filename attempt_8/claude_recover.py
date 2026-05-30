'''Claude-as-proposer ralph loop runner.
Picks a stage + chain, calls run_chain, returns trajectory dict.

Usage:
  python3 claude_recover.py --slug <slug> --chain-file my_chain.json
'''
import os, sys, json, argparse, time

sys.path.insert(0, '/home/vmihaylov/java_8_11_17_to_java_21/attempt_7/tools')
from iterate_repo import run_chain, OUT_DIR

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage-json', required=True, help='inline JSON for stage')
    ap.add_argument('--chain-json', required=True, help='inline JSON for chain (list of [label, jdk, recipes])')
    ap.add_argument('--out', required=True, help='where to dump the trajectory dict')
    ap.add_argument('--test-conservation', action='store_true')
    args = ap.parse_args()
    stage = json.loads(args.stage_json)
    chain_raw = json.loads(args.chain_json)
    chain = [tuple(item) for item in chain_raw]
    print(f'== running stage={stage["repo"]} J{stage["jv_from"]}->J{stage["jv_to"]} ==', flush=True)
    print(f'   chain has {len(chain)} steps', flush=True)
    t0 = time.time()
    traj = run_chain(stage, chain, test_conservation=args.test_conservation)
    elapsed = time.time() - t0
    print(f'== done in {elapsed:.0f}s: final_status={traj.get("final_status")} ==', flush=True)
    if traj.get('regressed_count'):
        print(f'   regressed_count={traj["regressed_count"]}')
    for s in traj.get('steps', []):
        print(f'   step={s["step"]:30s} rc_recipe={s.get("recipe_rc")} rc_build={s.get("build_rc")}')
    json.dump(traj, open(args.out, 'w'), indent=2, default=str)
    print(f'   trajectory saved to {args.out}')

if __name__ == '__main__':
    main()

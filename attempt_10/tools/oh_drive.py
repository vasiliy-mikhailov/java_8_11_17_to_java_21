"""attempt_10 driver — OpenHands executes the ff #1 prompt end-to-end on one stage.

For ONE slug:
  1. Fetch source at sha_from to workdir (shallow_fetch).
  2. Pre-test: docker_phase build under jv_from -> parse surefire -> pre_pass set.
  3. Run agent: OpenHands Conversation in workdir, prompt from attempt_10/prompt.md,
     condenser configured (ff #7), event sink to /var/log/observe/openhands.jsonl.
  4. Post-test: docker_phase build under jv_to -> parse surefire -> post_pass set.
  5. Score: check_test_conservation(pre_pass, post_pass).
  6. Write trajectory.json under attempt_10/per_repo_iter/<slug>/ with the new
     attempt_10 schema (agent runtime + backend + prompt fingerprint + event-
     stream summary + verdict + failure observation + wall + diff vs sha_from).

Usage:  python3 oh_drive.py <slug>
"""
import os, sys, json, time, hashlib, uuid, tempfile, shutil, subprocess

os.environ.setdefault('OPENHANDS_SUPPRESS_BANNER', '1')
for ln in open('/home/vmihaylov/java_8_11_17_to_java_21/.env'):
    ln = ln.strip()
    if not ln or ln.startswith('#') or '=' not in ln: continue
    k, v = ln.split('=', 1); v = v.strip().strip('"').strip("'")
    os.environ.setdefault(k, v)

BASE = '/home/vmihaylov/java_8_11_17_to_java_21'
sys.path.insert(0, f'{BASE}/attempt_7/tools')
from run_sequenced_java import shallow_fetch, docker_phase  # noqa: E402
from test_conservation import (  # noqa: E402
    parse_surefire_dir, check_test_conservation, fmt_regression, clear_surefire,
)

ATTEMPT_10 = f'{BASE}/attempt_10'
PROMPT_PATH = f'{ATTEMPT_10}/prompt.md'
TRAJ_DIR = f'{ATTEMPT_10}/per_repo_iter'
os.makedirs(TRAJ_DIR, exist_ok=True)

DATASET_TRAJ = f'{BASE}/attempt_9/per_repo_iter'  # source of stage definitions


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def main():
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(2)
    slug = sys.argv[1]
    stage_traj = f'{DATASET_TRAJ}/{slug}/trajectory.json'
    stage = json.load(open(stage_traj))['stage']
    print(f'=== stage: {stage["repo"]} {stage["jv_from"]}->{stage["jv_to"]} sha={stage["sha_from"][:10]}', flush=True)

    out = f'{TRAJ_DIR}/{slug}'
    os.makedirs(out, exist_ok=True)
    logs = f'{out}/logs'; os.makedirs(logs, exist_ok=True)

    # 1. Fetch source
    workdir = tempfile.mkdtemp(prefix=f'oh_drive_{slug[:24]}_')
    print(f'=== fetching to {workdir}', flush=True)
    if not shallow_fetch(stage['repo'], stage['sha_from'], workdir):
        print('FETCH_FAIL'); sys.exit(3)

    # 2. Pre-test under jv_from
    print(f'\n=== pre-test (mvn test under jdk{stage["jv_from"]})', flush=True)
    clear_surefire(workdir)
    t0 = time.time()
    rc_pre, log_pre = docker_phase(workdir, '/tmp', logs, 'test_pre',
                                    stage['jv_from'], timeout=900)
    pre_passed, pre_failed = parse_surefire_dir(workdir)
    print(f'    rc={rc_pre}  passed={len(pre_passed)}  failed={len(pre_failed)}  wall={int(time.time()-t0)}s', flush=True)

    if not pre_passed:
        print('=== pre_passed is empty; test conservation degenerates to compile-only PASS')
    pre_pass_count = len(pre_passed)

    # 3. Run agent
    prompt = open(PROMPT_PATH).read()
    prompt_fp = fingerprint(prompt)
    print(f'\n=== agent run (OpenHands SDK; prompt fingerprint {prompt_fp})', flush=True)
    print(f'=== workdir: {workdir}', flush=True)

    from openhands.sdk import LLM, Agent, Conversation, LocalWorkspace
    from openhands.tools.preset.default import get_default_tools
    from openhands.sdk.context.condenser import LLMSummarizingCondenser
    from openhands.sdk.event import MessageEvent
    from pydantic import SecretStr
    sys.path.insert(0, f'{ATTEMPT_10}/tools')
    from oh_event_sink import make_callback as oh_make_sink_callback

    llm = LLM(
        model=f'openai/{os.environ["VLLM_MODEL"]}',
        base_url=os.environ['VLLM_BASE_URL'],
        api_key=SecretStr(os.environ['VLLM_API_KEY']),
        usage_id=f'oh_drive_{slug[:40]}',
        max_output_tokens=4096,
        temperature=0.0,
        native_tool_calling=True,
    )
    compactor_llm = LLM(
        model=f'openai/{os.environ["COMPACTOR_VLLM_MODEL"]}',
        base_url=os.environ['COMPACTOR_VLLM_BASE_URL'],
        api_key=SecretStr(os.environ['COMPACTOR_VLLM_API_KEY']),
        usage_id=f'oh_drive_condenser_{slug[:40]}',
        max_output_tokens=4096,
        temperature=0.0,
        native_tool_calling=False,
    )
    condenser = LLMSummarizingCondenser(llm=compactor_llm, max_size=40, keep_first=2)
    agent = Agent(llm=llm,
                  tools=get_default_tools(enable_browser=False),
                  condenser=condenser)
    _conv_id = uuid.uuid4()
    _sink_cb = oh_make_sink_callback(_conv_id, slug=slug)
    conv = Conversation(agent=agent,
                        workspace=LocalWorkspace(working_dir=workdir),
                        conversation_id=_conv_id,
                        callbacks=[_sink_cb],
                        max_iteration_per_run=80)
    t_agent_start = time.time()
    conv.send_message(prompt)
    conv.run()
    agent_wall = round(time.time() - t_agent_start, 1)
    print(f'\n=== agent done: {len(conv.state.events)} events, wall={agent_wall}s', flush=True)

    # Event-stream summary
    by_event = {}; by_tool = {}; condense_count = 0
    for ev in conv.state.events:
        et = type(ev).__name__
        by_event[et] = by_event.get(et, 0) + 1
        tn = getattr(ev, 'tool_name', None)
        if tn: by_tool[tn] = by_tool.get(tn, 0) + 1
        if et == 'Condensation': condense_count += 1
    event_summary = {'by_event_type': by_event, 'by_tool': by_tool,
                     'condense_count': condense_count, 'total': len(conv.state.events)}

    # Last agent text (for bail messages)
    last_text = ''
    for ev in conv.state.events:
        if isinstance(ev, MessageEvent) and ev.source == 'agent':
            for c in ev.llm_message.content:
                t = getattr(c, 'text', '') or ''
                if t: last_text = t

    # 4. Post-test under jv_to
    print(f'\n=== post-test (mvn test under jdk{stage["jv_to"]})', flush=True)
    clear_surefire(workdir)
    t0 = time.time()
    rc_post, log_post = docker_phase(workdir, '/tmp', logs, 'test_post',
                                      stage['jv_to'], timeout=900)
    post_passed, post_failed = parse_surefire_dir(workdir)
    print(f'    rc={rc_post}  passed={len(post_passed)}  failed={len(post_failed)}  wall={int(time.time()-t0)}s', flush=True)

    # 5. Score
    if pre_pass_count == 0:
        verdict = 'PASS_compile_only' if rc_post == 0 else 'FAIL_build_post'
        regressed = set()
    else:
        ok, regressed = check_test_conservation(pre_passed, post_passed)
        if rc_post != 0:
            verdict = 'FAIL_build_post'
        elif ok:
            verdict = 'PASS'
        else:
            verdict = 'FAIL_test_conservation'

    print(f'\n=== VERDICT: {verdict}')
    if regressed:
        print(f'    regressed: {len(regressed)} tests')
        print(fmt_regression(regressed))

    # 6. Diff vs sha_from
    diff_path = f'{out}/migrated.diff'
    diff_rc = subprocess.run(['git', '-C', workdir, 'diff', '--no-index', '--stat',
                              '/dev/null', workdir], capture_output=True).returncode
    # Just produce a tarball of changes and a unified diff against sha_from
    diff_out = subprocess.run(
        ['bash', '-c',
         f'cd {workdir} && git init -q && git add -A && git diff --cached --stat'],
        capture_output=True).stdout.decode(errors='replace')
    open(diff_path, 'w').write(diff_out[:50000])

    trajectory = {
        'attempt': 'attempt_10',
        'slug': slug,
        'stage': stage,
        'agent_runtime': 'openhands-sdk-1.17',
        'backend_model': os.environ['VLLM_MODEL'],
        'prompt_fingerprint': prompt_fp,
        'verdict': verdict,
        'pre_pass_count': pre_pass_count,
        'post_pass_count': len(post_passed),
        'regressed_test_count': len(regressed),
        'regressed_tests': sorted([f'{c}.{m}' for (c, m) in regressed])[:50],
        'event_stream_summary': event_summary,
        'agent_wall_s': agent_wall,
        'rc_pre': rc_pre, 'rc_post': rc_post,
        'last_agent_text': last_text[-1500:],
        'workdir': workdir,
    }
    with open(f'{out}/trajectory.json', 'w') as f:
        json.dump(trajectory, f, indent=2)
    print(f'\n=== trajectory: {out}/trajectory.json')
    print(f'=== workdir kept for inspection: {workdir}')


if __name__ == '__main__':
    main()

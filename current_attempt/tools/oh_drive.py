"""Rung-3 driver (active attempt) — OpenHands executes the bump skill end-to-end on one stage.

For ONE slug:
  1. Fetch source at sha_from to workdir (shallow_fetch).
  2. Pre-test: docker_phase build under jv_from -> parse surefire -> pre_pass set.
  3. Run agent: OpenHands Conversation in workdir, prompt from the active attempt skill,
     condenser configured (ff #7), event sink to /var/log/observe/openhands.jsonl.
  4. Post-test: docker_phase build under jv_to -> parse surefire -> post_pass set.
  5. Score: check_test_conservation(pre_pass, post_pass).
  6. Write trajectory.json under current_attempt/per_repo_iter/<slug>/ with the
     attempt schema (agent runtime + backend + prompt fingerprint + event-
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
sys.path.insert(0, f'{BASE}/attempt_7/tools')                          # unmodified shared helpers (test_conservation)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))        # active attempt OWNS its build harness (run_sequenced_java -> sibling run_one_stage_v2.sh)
from run_sequenced_java import shallow_fetch, docker_phase  # noqa: E402  # resolves to the active-attempt copy
from test_conservation import (  # noqa: E402
    parse_surefire_dir, check_test_conservation, fmt_regression, clear_surefire,
)

ACTIVE = f'{BASE}/current_attempt'                 # operator-moved pointer to the open attempt
ATTEMPT_NAME = os.path.basename(os.path.realpath(ACTIVE))
SKILLS_DIR = f'{ACTIVE}/.agents/skills'   # bump-java-version skill -> agent_context (trigger-less = always active)
TRAJ_DIR = f'{ACTIVE}/per_repo_iter'
os.makedirs(TRAJ_DIR, exist_ok=True)
DATASET = f'{ACTIVE}/dataset-shas.json'           # stage source: the active attempt's dataset


def load_stage(slug):
    """Resolve a slug to a stage from the active attempt's dataset-shas.json.
    Slug convention: '<owner>_<repo>_<sha[:12]>' (repo '/' -> '_')."""
    for d in json.load(open(DATASET)):
        if f"{d['repo'].replace('/', '_')}_{d['sha'][:12]}" == slug:
            return {'repo': d['repo'], 'jv_from': d['jv_from'],
                    'jv_to': d['jv_to'], 'sha_from': d['sha']}
    raise SystemExit(f"slug {slug!r} not in {DATASET}")


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def main():
    if len(sys.argv) != 2:
        print(__doc__); sys.exit(2)
    slug = sys.argv[1]
    stage = load_stage(slug)
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
    prompt = (f"Bump this Maven project from Java {stage['jv_from']} to Java "
              f"{stage['jv_to']} using the bump-java-version skill.")
    prompt_fp = fingerprint(prompt)
    print(f'\n=== agent run (OpenHands SDK; prompt fingerprint {prompt_fp})', flush=True)
    print(f'=== workdir: {workdir}', flush=True)

    from openhands.sdk import LLM, Agent, Conversation, LocalWorkspace
    from openhands.sdk.skills import load_skills_from_dir
    from openhands.sdk.context.agent_context import AgentContext
    from openhands.tools.preset.default import get_default_tools
    from openhands.sdk.context.condenser import LLMSummarizingCondenser
    from openhands.sdk.event import MessageEvent
    from pydantic import SecretStr
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from oh_event_sink import make_callback as oh_make_sink_callback

    llm = LLM(
        model=f'openai/{os.environ["PROPOSER_MODEL"]}',
        base_url=os.environ['PROPOSER_BASE_URL'],
        api_key=SecretStr(os.environ['PROPOSER_API_KEY']),
        usage_id=f'oh_drive_{slug[:40]}',
        max_output_tokens=4096,
        temperature=0.0,
        native_tool_calling=True,
    )
    compactor_llm = LLM(
        model=f'openai/{os.environ["OPENHANDS_CONTEXT_COMPACTOR_MODEL"]}',
        base_url=os.environ['OPENHANDS_CONTEXT_COMPACTOR_BASE_URL'],
        api_key=SecretStr(os.environ['OPENHANDS_CONTEXT_COMPACTOR_API_KEY']),
        usage_id=f'oh_drive_condenser_{slug[:40]}',
        max_output_tokens=4096,
        temperature=0.0,
        native_tool_calling=False,
    )
    condenser = LLMSummarizingCondenser(llm=compactor_llm, max_size=40, keep_first=2)
    _merged = {}
    for _d in load_skills_from_dir(SKILLS_DIR):
        if isinstance(_d, dict): _merged.update(_d)
    skills = [_s for _n, _s in _merged.items() if _n == 'bump-java-version']
    print(f'=== agent_context skills: {[_s.name for _s in skills]} (always-active)', flush=True)
    agent = Agent(llm=llm,
                  tools=get_default_tools(enable_browser=False),
                  condenser=condenser,
                  agent_context=AgentContext(skills=skills, load_user_skills=False, load_public_skills=False))
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

    # 3b. Harness-applied deterministic compat layer (does NOT depend on the agent
    #     completing the bump script). The Qwen agent often runs the bump as its last
    #     action and hits the iteration/time limit before the bump script's compat tail
    #     lands, so the recurring Java-EE/Jadira fixes never reach the poms. Apply them
    #     here, after the agent and before the post-test. java11_compat.sh is pure-Python
    #     pom edits and idempotent, so it's a no-op if the agent already applied them.
    harness_compat = None
    if (int(stage['jv_from']), int(stage['jv_to'])) == (8, 11):
        compat_sh = f'{SKILLS_DIR}/bump-java-version/scripts/java11_compat.sh'
        print(f'\n=== harness compat: java11_compat.sh {workdir}', flush=True)
        cp = subprocess.run(['bash', compat_sh, workdir], capture_output=True, text=True)
        compat_log = (cp.stdout or '') + (cp.stderr or '')
        open(f'{logs}/java11_compat.log', 'w').write(compat_log)
        harness_compat = {'rc': cp.returncode,
                          'added_ee': 'added EE deps' in compat_log,
                          'jadira_override': 'java.version override added' in compat_log,
                          'build_plugin_bump': 'bumped build plugin' in compat_log}
        print(f'    compat rc={cp.returncode}  {harness_compat}', flush=True)

    # 4. Post-test under jv_to
    print(f'\n=== post-test (mvn test under jdk{stage["jv_to"]})', flush=True)
    clear_surefire(workdir)
    t0 = time.time()
    rc_post, log_post = docker_phase(workdir, '/tmp', logs, 'test_post',
                                      stage['jv_to'], timeout=900)
    post_passed, post_failed = parse_surefire_dir(workdir)
    print(f'    rc={rc_post}  passed={len(post_passed)}  failed={len(post_failed)}  wall={int(time.time()-t0)}s', flush=True)

    # 5. Score. rc_post is the `mvn test` exit code -- non-zero when tests merely ERROR,
    # not only when compilation fails. Compile success = the build reached the test phase
    # (or succeeded outright). Baseline-failing tests are excluded from conservation, so a
    # repo whose only tests error at baseline still PASSes (compile-only) once it compiles.
    compile_ok = (rc_post == 0) or ('Tests run:' in (log_post or ''))
    if not compile_ok:
        verdict = 'FAIL_build_post'
        regressed = set()
    elif pre_pass_count == 0:
        verdict = 'PASS_compile_only'
        regressed = set()
    else:
        ok, regressed = check_test_conservation(pre_passed, post_passed)
        verdict = 'PASS' if ok else 'FAIL_test_conservation'

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
        'attempt': ATTEMPT_NAME,
        'slug': slug,
        'stage': stage,
        'agent_runtime': 'openhands-sdk-1.17',
        'backend_model': os.environ['PROPOSER_MODEL'],
        'prompt_fingerprint': prompt_fp,
        'verdict': verdict,
        'pre_pass_count': pre_pass_count,
        'post_pass_count': len(post_passed),
        'regressed_test_count': len(regressed),
        'regressed_tests': sorted([f'{c}.{m}' for (c, m) in regressed])[:50],
        'event_stream_summary': event_summary,
        'harness_compat': harness_compat,
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

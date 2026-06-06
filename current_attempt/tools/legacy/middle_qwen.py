#!/usr/bin/env python3
"""D3 'qwen' rung: minimal Claude-scaffolding harness running Qwen as the tool-LLM.

Claude is the loop (this script); Qwen is the tool-using model called turn-by-turn.
Qwen sees the artifact prompt + a Stage header, can call execute_bash (which runs on
the LOCAL host where this script runs, i.e., the workdir host). Loops until Qwen
returns no tool_calls or hits max_turns.

Mutation rights: NONE. The artifact prompt is read verbatim; this rung only validates.
Whole-dialogue preservation: the FULL dialogue (system prompt + every turn, untruncated,
with full tool args and full bash output) is written to per_repo_iter/<slug>/dialogue.qwen.log,
and the full message list Qwen saw to dialogue.qwen.messages.json. Only what is *fed back
to Qwen* per tool result is capped (MAX_ACTION_OUTPUT) for context budget; the log keeps all.

Usage: middle_qwen.py <slug> <workdir> <jv_from> <jv_to>
"""
import os, sys, json, subprocess, time
from openai import OpenAI

# load .env
for ln in open('/home/vmihaylov/java_8_11_17_to_java_21/.env'):
    ln = ln.strip()
    if not ln or ln.startswith('#') or '=' not in ln: continue
    k, v = ln.split('=', 1); v = v.strip().strip('"').strip("'")
    os.environ.setdefault(k, v)

ATTEMPT_DIR = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"
PROMPT_PATH = f"{ATTEMPT_DIR}/.agents/skills/bump-java-version/SKILL.md"
MAX_TURNS = 80
MAX_ACTION_OUTPUT = 8000  # cap on what Qwen SEES per tool result (context budget); full output is still logged

slug, workdir, jv_from, jv_to = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]

# Persist the WHOLE dialogue per-stage (stable path, rung-specific name) -- not transient /tmp.
stage_dir = f'{ATTEMPT_DIR}/per_repo_iter/{slug}'
os.makedirs(stage_dir, exist_ok=True)
log_path = f'{stage_dir}/dialogue.qwen.log'
msgs_path = f'{stage_dir}/dialogue.qwen.messages.json'

client = OpenAI(base_url=os.environ['PROPOSER_BASE_URL'], api_key=os.environ['PROPOSER_API_KEY'])
prompt_text = open(PROMPT_PATH).read()

stage_header = f'''## Stage (injected by qwen-rung harness)
- repo workdir: {workdir}
- jv_from: {jv_from}
- jv_to: {jv_to}
- slug: {slug}
- you are running under Claude+Qwen (qwen rung); the harness executes your tool_calls on the host via bash

'''

system_message = stage_header + prompt_text

tools = [{
    'type': 'function',
    'function': {
        'name': 'execute_bash',
        'description': 'Run a bash command on the host. Returns stdout+stderr+rc.',
        'parameters': {
            'type': 'object',
            'properties': {
                'cmd': {'type': 'string', 'description': 'bash command to run'},
                'timeout_seconds': {'type': 'integer', 'description': 'timeout, default 120', 'default': 120}
            },
            'required': ['cmd']
        }
    }
}, {
    'type': 'function',
    'function': {
        'name': 'finish',
        'description': 'Call when the bump is done (PASS, BAIL with label, or exhausted).',
        'parameters': {
            'type': 'object',
            'properties': {
                'outcome': {'type': 'string', 'description': 'PASS or BAIL:<label> or FAIL:<reason>'},
                'summary': {'type': 'string', 'description': 'brief summary'}
            },
            'required': ['outcome', 'summary']
        }
    }
}]

messages = [{'role': 'system', 'content': system_message},
            {'role': 'user', 'content': f'Execute the Java LTS bump for the stage above. Use execute_bash to run commands; call finish when done.'}]

def run_bash(cmd, timeout=120):
    try:
        p = subprocess.run(['bash', '-c', cmd], capture_output=True, text=True, timeout=timeout)
        return f'rc={p.returncode}\n' + (p.stdout + p.stderr)  # FULL output (not capped here)
    except subprocess.TimeoutExpired:
        return f'TIMEOUT after {timeout}s'

start = time.time()
log = open(log_path, 'w')
log.write(f'=== qwen rung starting on {slug} workdir={workdir} jv={jv_from}->{jv_to} ts={time.strftime("%Y-%m-%d %H:%M:%S")}\n')
log.write(f'=== SYSTEM (artifact prompt + stage header) ===\n{system_message}\n=== END SYSTEM ===\n')
log.write(f'=== USER ===\n{messages[1]["content"]}\n')
log.flush()

terminal = None
turn = 0
for turn in range(MAX_TURNS):
    try:
        resp = client.chat.completions.create(
            model=os.environ['PROPOSER_MODEL'],
            messages=messages, tools=tools, tool_choice='auto',
            temperature=0.0, max_tokens=4096, timeout=120
        )
    except Exception as e:
        log.write(f'turn {turn} LLM error: {e}\n'); break
    msg = resp.choices[0].message
    log.write(f'\n--- turn {turn} ---\nassistant: {msg.content or ""}\n')
    if msg.tool_calls:
        for tc in msg.tool_calls:
            log.write(f'tool_call: {tc.function.name}({tc.function.arguments})\n')
    log.flush()
    messages.append({'role': 'assistant', 'content': msg.content, 'tool_calls': [{'id': tc.id, 'type': 'function', 'function': {'name': tc.function.name, 'arguments': tc.function.arguments}} for tc in msg.tool_calls] if msg.tool_calls else None})
    if not msg.tool_calls:
        log.write('no tool_calls -- assuming terminal\n')
        terminal = {'outcome': 'FAIL:no_tool_calls', 'summary': (msg.content or '')[:200]}
        break
    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        if tc.function.name == 'finish':
            terminal = args
            messages.append({'role': 'tool', 'tool_call_id': tc.id, 'content': 'acknowledged'})
            log.write(f'FINISH: {args}\n')
            break
        elif tc.function.name == 'execute_bash':
            result = run_bash(args['cmd'], args.get('timeout_seconds', 120))
            log.write(f'result (full):\n{result}\n')
            log.flush()
            messages.append({'role': 'tool', 'tool_call_id': tc.id, 'content': result[:MAX_ACTION_OUTPUT]})
    if terminal: break

wall = time.time() - start
log.write(f'\n=== DONE wall={wall:.1f}s turns={turn+1} terminal={terminal}\n')
log.close()
# whole-dialogue machine-readable record (every message Qwen saw, in order)
json.dump(messages, open(msgs_path, 'w'), indent=2, default=str)

# emit a compact summary to stdout for the caller
print(json.dumps({'slug': slug, 'wall_seconds': wall, 'turns': turn+1, 'terminal': terminal, 'log': log_path, 'messages': msgs_path}))

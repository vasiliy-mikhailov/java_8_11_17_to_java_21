#!/usr/bin/env python3
"""Continuous sliding-window corpus runner.

Keeps N workers in-flight at all times. As each tmux session emits DONE,
runs the persistence wrapper and immediately launches the next pending stage.
Stages drawn from /tmp/corpus_batch_plan.json minus what's already in feedback.jsonl.

Usage: corpus_continuous.py [N=8] [max_stages=999]

Stops when (a) max_stages new outer trajectories emitted, or (b) queue empty + all workers idle.
"""
import os, sys, json, subprocess, time, glob, xml.etree.ElementTree as ET

ATTEMPT_DIR = '/home/vmihaylov/java_8_11_17_to_java_21/current_attempt'
PROMPT_PATH = f'{ATTEMPT_DIR}/prompt.md'
FEEDBACK_JSONL = f'{ATTEMPT_DIR}/feedback.jsonl'
PLAN = '/tmp/corpus_batch_plan.json'
PERSIST = f'{ATTEMPT_DIR}/tools/d10_outer_persist.py'

N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
MAX_NEW = int(sys.argv[2]) if len(sys.argv) > 2 else 999
RUNNER_LOG = f'/tmp/corpus_continuous_{int(time.time())}.log'

def log(msg):
    s = f'[{time.strftime("%H:%M:%S")}] {msg}'
    print(s, flush=True)
    with open(RUNNER_LOG, 'a') as f: f.write(s + '\n')

def sh(cmd, timeout=60):
    return subprocess.run(['bash','-c',cmd], capture_output=True, text=True, timeout=timeout)

def already_done():
    done = set()
    if not os.path.exists(FEEDBACK_JSONL): return done
    for l in open(FEEDBACK_JSONL):
        try: d = json.loads(l)
        except: continue
        if d.get('level') == 'outer': done.add(d['stage'])
    return done

def surefire_counts(workdir):
    t=f=e=sk=0; passing=[]
    for x in glob.glob(f'{workdir}/**/target/surefire-reports/TEST-*.xml', recursive=True):
        try:
            r = ET.parse(x).getroot()
            t+=int(r.get('tests',0)); f+=int(r.get('failures',0))
            e+=int(r.get('errors',0)); sk+=int(r.get('skipped',0))
            for tc in r.findall('testcase'):
                if tc.find('failure') is None and tc.find('error') is None:
                    passing.append(tc.get('classname','?')+'::'+tc.get('name','?'))
        except: pass
    return {'tests':t,'failures':f,'errors':e,'skipped':sk,'passing':passing}

def prep_stage(s):
    """Clone, checkout, capture pre-baseline, git init. Returns dict with wd, pre_path, has_pom, or None on failure."""
    slug_short = s['slug'].split('_')[0][:8].lower()
    wd = f'/tmp/bx_{slug_short}_oh'
    sh(f'docker run --rm --entrypoint bash -v /tmp:/host j21-fitness:latest -c "rm -rf /host/bx_{slug_short}_oh" 2>/dev/null')
    sh(f'rm -rf {wd}', timeout=20)
    sh(f'git clone --quiet --depth 80 https://github.com/{s["repo"]} {wd} 2>&1 | tail -1', timeout=120)
    sh(f'cd {wd} && git fetch --quiet --depth 200 origin {s["sha"]} 2>&1 | tail -1', timeout=120)
    co = sh(f'cd {wd} && git checkout --quiet {s["sha"]} 2>&1', timeout=60)
    if co.returncode != 0:
        sh(f'cd {wd} && git fetch --quiet --unshallow', timeout=300)
        sh(f'cd {wd} && git checkout --quiet {s["sha"]}', timeout=60)
    sh(f'rm -rf {wd}/.git {wd}/target')
    if not os.path.exists(f'{wd}/pom.xml'):
        return {'slug': s['slug'], 'wd': wd, 'has_pom': False, 'pre_path': None}
    # pre baseline
    sh(f'cd {wd} && PATH=$HOME/bin:$PATH JDK=17 mvn -B -ntp test > /dev/null 2>&1', timeout=600)
    pre = surefire_counts(wd)
    pre_path = f'/tmp/bx_pre_{s["slug"][:30]}_{int(time.time())}.json'
    json.dump(pre, open(pre_path, 'w'))
    # clean target as root, git init baseline
    sh(f'docker run --rm --entrypoint bash -v {wd}:/work j21-fitness:latest -c "rm -rf /work/target" 2>/dev/null')
    sh(f'cd {wd} && git init -q && git add -A && git commit -q -m baseline')
    return {'slug': s['slug'], 'wd': wd, 'has_pom': True, 'pre_path': pre_path, 'pre_passing': len(pre['passing']), 'sha': s['sha']}

def launch_oh(prepped):
    """Launch oh_one.py in a tmux session. Returns log path."""
    slug_short = prepped['slug'].split('_')[0][:8].lower()
    # session name unique enough to coexist with other workers
    sess = f'cb_{slug_short}_{int(time.time())%10000}'
    log_path = f'/tmp/{sess}.log'
    open(log_path, 'w').close()
    cmd = f'cd /tmp && PATH=$HOME/bin:/tmp:$PATH python3 /tmp/oh_one.py {prepped["wd"]} {prepped["slug"]} 2>&1 | tee {log_path}'
    sh(f'tmux new-session -d -s {sess} "bash -lc \'{cmd}\'"', timeout=10)
    return {'sess': sess, 'log': log_path, **prepped}

def check_done(worker):
    r = sh(f'grep "^=== DONE" {worker["log"]} 2>/dev/null | tail -1', timeout=10)
    return r.stdout.strip() != ''

def run_persist(worker):
    sh(f'python3 {PERSIST} {worker["slug"]} {worker["wd"]} {worker["log"]} 17 21 {worker["pre_path"]}', timeout=60)
    # kill tmux session
    sh(f'tmux kill-session -t {worker["sess"]} 2>/dev/null', timeout=5)

def main():
    plan = json.load(open(PLAN))
    done = already_done()
    queue = [s for s in plan if s['slug'] not in done]
    log(f'queue: {len(queue)} stages pending; N={N}; max_new={MAX_NEW}')

    workers = []  # list of dicts {sess, log, slug, wd, pre_path, has_pom, pre_passing, sha}
    new_count = 0

    # Initial fill: launch N stages
    while len(workers) < N and queue and new_count < MAX_NEW:
        s = queue.pop(0)
        log(f'prep {s["slug"]}')
        try:
            prepped = prep_stage(s)
        except Exception as e:
            log(f'PREP FAIL {s["slug"]}: {e}'); continue
        if not prepped['has_pom']:
            log(f'SKIP {s["slug"]} no root pom')
            continue
        w = launch_oh(prepped)
        log(f'launched {w["sess"]} pre_passing={prepped["pre_passing"]}')
        workers.append(w)

    log(f'initial workers in flight: {len(workers)}')

    # Sliding window: poll, replace as each DONEs
    while workers and new_count < MAX_NEW:
        time.sleep(20)
        finished = [w for w in workers if check_done(w)]
        for w in finished:
            workers.remove(w)
            log(f'DONE {w["slug"]}; running wrapper')
            try: run_persist(w)
            except Exception as e: log(f'PERSIST FAIL {w["slug"]}: {e}')
            new_count += 1
            log(f'new_count={new_count}/{MAX_NEW}; queue={len(queue)}; in_flight={len(workers)}')
            # refill
            while len(workers) < N and queue and new_count + len(workers) < MAX_NEW:
                s = queue.pop(0)
                log(f'prep {s["slug"]}')
                try:
                    prepped = prep_stage(s)
                except Exception as e:
                    log(f'PREP FAIL {s["slug"]}: {e}'); continue
                if not prepped['has_pom']:
                    log(f'SKIP {s["slug"]} no root pom')
                    continue
                w2 = launch_oh(prepped)
                log(f'launched {w2["sess"]} pre_passing={prepped["pre_passing"]}')
                workers.append(w2)

    # drain remaining workers
    while workers:
        time.sleep(20)
        finished = [w for w in workers if check_done(w)]
        for w in finished:
            workers.remove(w)
            log(f'DONE {w["slug"]}; running wrapper')
            try: run_persist(w)
            except: pass
            new_count += 1

    log(f'=== continuous runner done: {new_count} new outer trajectories emitted; log {RUNNER_LOG}')

if __name__ == '__main__': main()

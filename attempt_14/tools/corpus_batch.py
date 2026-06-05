#!/usr/bin/env python3
"""Corpus batch runner — picks N untested stages and runs them through D10 outer in parallel.

Usage: corpus_batch.py <N> [<offset>]
- N: how many stages to run in parallel this batch (default 8)
- offset: skip first M from the remaining list (default 0; for picking different batches)

Reads /tmp/corpus_batch_plan.json (list of {repo, sha, slug}).
Excludes slugs already in feedback.jsonl as outer entries.
Preps each workdir, captures pre-baseline (parallel), git inits, launches tmux session,
polls until all DONE markers, runs persistence wrapper on each. Logs to /tmp/corpus_batch_<ts>.log.
"""
import os, sys, json, subprocess, time, glob, xml.etree.ElementTree as ET

ATTEMPT_DIR = '/home/vmihaylov/java_8_11_17_to_java_21/current_attempt'
PROMPT_PATH = f'{ATTEMPT_DIR}/prompt.md'
FEEDBACK_JSONL = f'{ATTEMPT_DIR}/feedback.jsonl'
PLAN = '/tmp/corpus_batch_plan.json'

N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
OFFSET = int(sys.argv[2]) if len(sys.argv) > 2 else 0

def sh(cmd, timeout=120):
    return subprocess.run(['bash','-c',cmd], capture_output=True, text=True, timeout=timeout)

def already_done():
    done = set()
    if not os.path.exists(FEEDBACK_JSONL): return done
    for l in open(FEEDBACK_JSONL):
        d = json.loads(l)
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

def main():
    plan = json.load(open(PLAN))
    done = already_done()
    pending = [s for s in plan if s['slug'] not in done]
    batch = pending[OFFSET:OFFSET+N]
    if not batch:
        print('nothing to run'); return
    print(f'=== batch: {len(batch)} stages')
    for s in batch: print(f"  {s['slug']}  sha={s['sha'][:10]}")
    ts = int(time.time())
    batchlog = f'/tmp/corpus_batch_{ts}.log'
    bl = open(batchlog,'w')

    # 1. clone + checkout (sequential — git is fast, parallel doesn't help much; avoids github rate-limit)
    print('=== clone + checkout')
    for s in batch:
        slug_short = s['slug'].split('_')[0][:8].lower()
        wd = f'/tmp/bx_{slug_short}_oh'
        s['wd'] = wd
        sh(f'docker run --rm --entrypoint bash -v /tmp:/host j21-fitness:latest -c "rm -rf /host/bx_{slug_short}_oh" 2>/dev/null')
        sh(f'rm -rf {wd}')
        r = sh(f'git clone --quiet --depth 80 https://github.com/{s["repo"]} {wd} 2>&1 | tail -1')
        sh(f'cd {wd} && git fetch --quiet --depth 200 origin {s["sha"]} 2>&1 | tail -1', timeout=120)
        co = sh(f'cd {wd} && git checkout --quiet {s["sha"]} 2>&1 | tail -1', timeout=60)
        if co.returncode != 0:
            sh(f'cd {wd} && git fetch --quiet --unshallow 2>&1 | tail', timeout=300)
            sh(f'cd {wd} && git checkout --quiet {s["sha"]}', timeout=60)
        sh(f'rm -rf {wd}/.git {wd}/target')
        has_pom = os.path.exists(f'{wd}/pom.xml')
        s['has_root_pom'] = has_pom
        bl.write(f'{s["slug"]}  pom={has_pom}\n')

    # 2. pre-baseline mvn test in parallel
    print('=== pre-baseline (parallel)')
    procs = {}
    for s in batch:
        if not s['has_root_pom']:
            s['pre'] = None
            continue
        pre_log = f'/tmp/bx_{s["slug"][:30]}_pre.log'
        procs[s['slug']] = (subprocess.Popen(['bash','-c',f'cd {s["wd"]} && PATH=$HOME/bin:$PATH JDK=17 mvn -B -ntp test > {pre_log} 2>&1'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL), s, pre_log)
    for slug, (p, s, pre_log) in procs.items():
        try:
            p.wait(timeout=600)
        except: p.kill()
        post = surefire_counts(s['wd'])
        s['pre'] = post
        bl.write(f'{slug}  pre tests={post["tests"]} fail={post["failures"]} err={post["errors"]} passing={len(post["passing"])}\n')
        pre_path = f'/tmp/bx_pre_{slug[:30]}.json'
        json.dump(post, open(pre_path,'w'))
        s['pre_path'] = pre_path
        # clean target as root + git init baseline
        sh(f'docker run --rm --entrypoint bash -v {s["wd"]}:/work j21-fitness:latest -c "rm -rf /work/target" 2>/dev/null')
        sh(f'cd {s["wd"]} && git init -q && git add -A && git commit -q -m baseline')

    # 3. launch oh_one.py in tmux for each (those with root pom)
    print('=== launching tmux sessions')
    sh('tmux kill-server 2>/dev/null', timeout=10)
    time.sleep(1)
    launched = []
    for s in batch:
        if not s['has_root_pom']:
            bl.write(f'{s["slug"]}  SKIP — no root pom\n')
            continue
        slug_short = s['slug'].split('_')[0][:8].lower()
        log = f'/tmp/cb_{slug_short}.log'
        s['log'] = log
        open(log,'w').close()
        cmd = f'cd /tmp && PATH=$HOME/bin:/tmp:$PATH python3 /tmp/oh_one.py {s["wd"]} {s["slug"]} 2>&1 | tee {log}'
        sh(f'tmux new-session -d -s cb_{slug_short} "bash -lc \'{cmd}\'"', timeout=10)
        launched.append(s)
    print(f'=== launched {len(launched)} sessions at {time.strftime("%H:%M:%S")}')

    # 4. poll until all DONE
    deadline = time.time() + 60*30  # 30min max
    while time.time() < deadline:
        time.sleep(30)
        not_done = []
        for s in launched:
            log = s['log']
            r = sh(f'grep -E "^=== DONE" {log} 2>/dev/null | tail -1')
            if not r.stdout.strip():
                not_done.append(s['slug'])
        print(f'[{time.strftime("%H:%M:%S")}] still running: {len(not_done)}/{len(launched)}', flush=True)
        if not not_done: break

    # 5. run persistence wrapper on each
    print('=== running persistence wrapper')
    for s in launched:
        sh(f'python3 {ATTEMPT_DIR}/tools/d10_outer_persist.py {s["slug"]} {s["wd"]} {s["log"]} 17 21 {s["pre_path"]}', timeout=60)

    bl.close()
    print(f'=== batch done, log: {batchlog}')

if __name__ == '__main__': main()

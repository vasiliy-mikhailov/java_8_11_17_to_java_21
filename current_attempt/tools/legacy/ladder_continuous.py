#!/usr/bin/env python3
"""Sliding-window P3 ladder sweep: keep N datapoint-ladders in flight; refill as they finish.
Each datapoint runs opus->qwen->oh sequentially (ladder_one.sh) and records 3 verdict rows
to feedback_p3_iter.jsonl (stage = <plan_slug>__iter1). Skips datapoints already fully done.
Usage: ladder_continuous.py [N=8] [max_new=99999]
"""
import os, sys, json, subprocess, time, re
T = '/home/vmihaylov/java_8_11_17_to_java_21/current_attempt'
PLAN = '/tmp/corpus_batch_plan.json'
FB = f'{T}/feedback_p3_iter.jsonl'
LADDER = f'{T}/tools/ladder_one.sh'
LOG = '/tmp/ladder_continuous.log'
N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
MAXNEW = int(sys.argv[2]) if len(sys.argv) > 2 else 99999

def log(s):
    open(LOG, 'a').write(time.strftime('%H:%M:%S ') + s + '\n')

def done_slugs():
    seen = {}
    if os.path.exists(FB):
        for l in open(FB):
            try: d = json.loads(l)
            except: continue
            seen.setdefault(d['stage'], set()).add(d['rung'])
    return {s for s, r in seen.items() if {'opus', 'qwen', 'oh_qwen'} <= r}

def main():
    plan = json.load(open(PLAN))
    done = done_slugs()
    queue = [s for s in plan if f"{s['slug']}__iter1" not in done and re.search(r'J(\d+)toJ(\d+)', s['slug'])]
    log(f'START queue={len(queue)} N={N} max_new={MAXNEW} already_done={len(done)}')
    inflight = {}; qi = 0; launched = 0; finished = 0
    while (qi < len(queue) and launched < MAXNEW) or inflight:
        while len(inflight) < N and qi < len(queue) and launched < MAXNEW:
            s = queue[qi]; qi += 1
            m = re.search(r'J(\d+)toJ(\d+)', s['slug'])
            slug = f"{s['slug']}__iter1"
            p = subprocess.Popen(['bash', LADDER, slug, s['repo'], s['sha'], m.group(1), m.group(2)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            inflight[p] = (slug, time.time()); launched += 1
            log(f'launch {slug}  inflight={len(inflight)} launched={launched}')
        time.sleep(5)
        for p in list(inflight):
            if p.poll() is not None:
                slug, t0 = inflight[p]; finished += 1
                log(f'finished {slug} rc={p.returncode} wall={int(time.time()-t0)}s finished={finished}')
                del inflight[p]
    log(f'ALL DONE launched={launched} finished={finished}')

if __name__ == '__main__':
    main()

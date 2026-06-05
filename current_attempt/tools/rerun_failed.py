import subprocess, time, sys
T='/home/vmihaylov/java_8_11_17_to_java_21/current_attempt'
N=int(sys.argv[1]) if len(sys.argv)>1 else 8
jobs=[l.split('\t') for l in open('/tmp/failed_oh.tsv').read().splitlines() if l.strip()]
LOG='/tmp/rerun_failed.log'
def log(s): open(LOG,'a').write(time.strftime('%H:%M:%S ')+s+'\n')
log(f'START rerun {len(jobs)} failed datapoints N={N}')
inflight={}; qi=0
while qi<len(jobs) or inflight:
    while len(inflight)<N and qi<len(jobs):
        slug,repo,sha=jobs[qi][:3]; qi+=1
        p=subprocess.Popen(['bash',f'{T}/tools/rerun_one_oh.sh',slug,repo,sha],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        inflight[p]=slug; log(f'launch {slug} ({len(inflight)} inflight {qi}/{len(jobs)})')
    time.sleep(5)
    for p in list(inflight):
        if p.poll() is not None: log(f'done {inflight[p]}'); del inflight[p]
log('ALL RERUN DONE')

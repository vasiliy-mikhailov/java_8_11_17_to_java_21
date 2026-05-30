#!/usr/bin/env python3
"""Frog's-eye (D10): multi-resolution NOVELTY detector over AGENT BEHAVIOUR, Vector-fed.
Reads Vector sinks only (/var/log/observe/app_logs.jsonl for the agent event stream + ladder
throughput; host_metrics.jsonl for load). Primes current state as background, then emits ONLY
changes-in-agents that did-not-happen-before (new error/bail signature, agent LOOP, iteration cap),
plus secondary stall/load spikes, by 10s/60s/5m/30m contrast. Silent on steady state; emit-on-edge.
Output: telemetry/frog_eye.jsonl + stdout. Usage: frog_eye.py [tick=10]"""
import json, collections, time, os, re, sys, subprocess
OBS='/var/log/observe'; T='/home/vmihaylov/java_8_11_17_to_java_21/attempt_10'; OUT=f'{T}/telemetry/frog_eye.jsonl'
def shtail(path,n):
    try: return subprocess.run(['tail','-n',str(n),path],capture_output=True,text=True,timeout=10).stdout.splitlines()
    except Exception: return []
def agent_events(n=3000):
    ev=[]
    for l in shtail(f'{OBS}/app_logs.jsonl',n):
        try: d=json.loads(l)
        except Exception: continue
        if str(d.get('file','')).endswith('agent_events.log'):
            m=re.match(r'(\d\d:\d\d:\d\d) AGENT (\S+) (\S+) (\S+) ?(.*)',d.get('message',''))
            if m: ev.append({'slug':m.group(2),'rung':m.group(3),'kind':m.group(4),'det':m.group(5).strip()})
    return ev
def finished_count(n=5000):
    return sum(1 for l in shtail(f'{OBS}/app_logs.jsonl',n) if '" finished "' not in l and ' finished ' in l and 'ladder_continuous.log' in l)
def load1(n=1500):
    v=None
    for l in shtail(f'{OBS}/host_metrics.jsonl',n):
        try: d=json.loads(l)
        except Exception: continue
        if d.get('name')=='load1':
            v=(d.get('gauge') or d.get('counter') or {}).get('value')
    return v
def main():
    tick=int(sys.argv[1]) if len(sys.argv)>1 else 10
    seen=set(); active=set(); loadbuf=collections.deque(); last_fin=None; last_fin_ts=time.time()
    def emit(kind,msg,**kw):
        rec={'iso':time.strftime('%Y-%m-%dT%H:%M:%S'),'kind':kind,'msg':msg}; rec.update(kw)
        open(OUT,'a').write(json.dumps(rec)+'\n'); print(f"[{rec['iso'][11:]}] {kind}: {msg}",flush=True)
    for e in agent_events(): seen.add((e['kind'],e['det'][:50]))
    last_fin=finished_count()
    print(f"[prime] background agent-signatures={len(seen)} finished={last_fin} -- emitting only NEW agent behaviour",flush=True)
    while True:
        time.sleep(tick); now=time.time()
        for e in agent_events():
            sig=(e['kind'],e['det'][:50])
            if e['kind'] in ('ERROR','BAIL','LOOP','MAXITER') and sig not in seen:
                seen.add(sig); emit(f"NOVEL_{e['kind']}", f"{e['det'][:70]} ({e['slug']}/{e['rung']})", slug=e['slug'], rung=e['rung'])
        fc=finished_count()
        if fc>last_fin: last_fin=fc; last_fin_ts=now
        if (now-last_fin_ts>300) and 'stall' not in active: active.add('stall'); emit('STALL',f"no ladder finished in {int(now-last_fin_ts)}s")
        if (now-last_fin_ts<=300) and 'stall' in active: active.discard('stall'); emit('CLEARED','finishes resumed')
        v=load1()
        if v is not None:
            loadbuf.append((now,v))
            while loadbuf and now-loadbuf[0][0]>1800: loadbuf.popleft()
            w10=[x for t,x in loadbuf if now-t<=20]; w30=[x for t,x in loadbuf if now-t<=1800]
            if w10 and len(w30)>=6:
                c=sum(w10)/len(w10); base=sorted(w30)[len(w30)*9//10]
                if c>max(base*1.4,30) and "loadspike" not in active: active.add("loadspike"); emit("SPIKE_LOAD",f"load {c:.1f} vs 30m-p90 {base:.1f}")
                if c<=base*1.15 and "loadspike" in active: active.discard("loadspike"); emit("CLEARED",f"load {c:.1f}")
if __name__=="__main__": main()

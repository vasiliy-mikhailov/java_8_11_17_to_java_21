#!/usr/bin/env python3
"""Agent-consumable sweep digest (deterministic, no LLM). One read = progress + failure-label
clusters + stuck rungs + resource spikes, with ALERT flags. Sources: feedback_p3_iter.jsonl,
ladder_continuous.log, live load/mem/disk/nvidia-smi. Prints + appends telemetry/sweep_digest.jsonl.
Usage: sweep_digest.py [loop [secs]]"""
import json, collections, subprocess, time, os, re, sys
T='/home/vmihaylov/java_8_11_17_to_java_21/current_attempt'
FB=f'{T}/feedback_p3_iter.jsonl'; MGR='/tmp/ladder_continuous.log'; NPROC=24
def sh(c):
    try: return subprocess.run(c,shell=True,capture_output=True,text=True,timeout=12).stdout.strip()
    except Exception: return ''
def gpus():
    out=sh("nvidia-smi --query-gpu=index,utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits"); r=[]
    for ln in out.splitlines():
        try: i,u,mu,mt=[x.strip() for x in ln.split(",")]; r.append((int(i),int(u),int(mu),int(mt)))
        except Exception: pass
    return r
def one():
    rows=[json.loads(l) for l in open(FB)] if os.path.exists(FB) else []
    agg=collections.defaultdict(collections.Counter); st=collections.defaultdict(dict); labels=collections.Counter()
    for d in rows:
        o=d.get("outcome",""); agg[d["rung"]][o.split(":")[0]]+=1; st[d["stage"]][d["rung"]]=o
        if o.startswith("BAIL:"): labels[o[5:]]+=1
    done=sum(1 for s,r in st.items() if {"opus","qwen","oh_qwen"}<=set(r))
    mgr=open(MGR).read() if os.path.exists(MGR) else ""
    launched=mgr.count("launch "); finished=mgr.count("finished ")
    inflight=int(sh("ps -eo args | grep -E \"bash [^ ]*ladder_one.sh\" | grep -v grep | wc -l") or 0)
    mgr_alive=int(sh("ps -eo args | grep ladder_continuous.py | grep -v grep | wc -l") or 0)>0
    stuck=[]
    for line in sh("ps -eo etimes,args | grep -E \"opus_rung.sh|middle_qwen.py|oh_one.py /tmp\" | grep -v grep").splitlines():
        m=re.match(r"\s*(\d+)\s+(.*)",line)
        if not m: continue
        et=int(m.group(1)); cmd=m.group(2)
        rung="opus" if "opus_rung" in cmd else ("qwen" if "middle_qwen" in cmd else "oh")
        thr={"opus":400,"qwen":500,"oh":640}[rung]
        if et>thr:
            sl=re.search(r"(\S+__J\d+toJ\d+__iter1)",cmd); stuck.append((rung,et,sl.group(1) if sl else "?"))
    load=open("/proc/loadavg").read().split()[:3]
    ml=sh("free -m | awk \"/Mem:/{print \\$3,\\$2}\"").split(); mu,mt=(int(ml[0]),int(ml[1])) if len(ml)==2 else (0,0)
    diskp=int(sh("df /tmp | awk \"NR==2{print \\$5}\" | tr -d %") or 0)
    G=gpus(); alerts=[]
    if float(load[0])>NPROC*1.25: alerts.append(f"CPU load {load[0]}>{int(NPROC*1.25)}")
    for i,u,xu,xt in G:
        if xt and xu/xt>0.93: alerts.append(f"GPU{i} mem {xu}/{xt}MiB(>93%)")
    if diskp>85: alerts.append(f"/tmp {diskp}% full")
    if mgr_alive and inflight<6 and launched>finished: alerts.append(f"window underfilled inflight={inflight}")
    if (not mgr_alive) and launched>finished: alerts.append("MANAGER DOWN (sweep incomplete)")
    for lab,c in labels.items():
        if c>=4: alerts.append(f"cluster {lab} x{c}")
    for rung,et,sl in stuck: alerts.append(f"STUCK {rung} {et}s {sl}")
    ts=time.strftime("%H:%M:%S")
    print(f"[{ts}] done={done} | opus {dict(agg['opus'])} | qwen {dict(agg['qwen'])} | oh {dict(agg['oh_qwen'])}")
    print(f"  window: inflight={inflight} launched={launched} finished={finished} mgr={'up' if mgr_alive else 'DOWN'}")
    print(f"  bail-labels: {dict(labels)}")
    print(f"  res: load {'/'.join(load)} (n={NPROC}) | mem {mu}/{mt}MB | /tmp {diskp}% | "+" ".join(f"GPU{i}:{u}%/{xu}MiB" for i,u,xu,xt in G))
    print("  ALERTS: "+("; ".join(alerts) if alerts else "none"))
    os.makedirs(f"{T}/telemetry",exist_ok=True)
    rec={"ts":time.time(),"iso":time.strftime("%Y-%m-%dT%H:%M:%S"),"done":done,"rung":{r:dict(agg[r]) for r in ["opus","qwen","oh_qwen"]},"labels":dict(labels),"inflight":inflight,"launched":launched,"finished":finished,"mgr_alive":mgr_alive,"load":load,"gpu":[list(g) for g in G],"alerts":alerts}
    open(f"{T}/telemetry/sweep_digest.jsonl","a").write(json.dumps(rec)+"\n")
if __name__=="__main__":
    if len(sys.argv)>1 and sys.argv[1]=="loop":
        s=int(sys.argv[2]) if len(sys.argv)>2 else 60
        while True:
            try: one()
            except Exception as e: print("digest error",e)
            time.sleep(s)
    else: one()

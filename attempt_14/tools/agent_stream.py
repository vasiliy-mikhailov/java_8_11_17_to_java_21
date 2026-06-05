#!/usr/bin/env python3
"""Agent event-stream emitter (fulfils D10's 'captured set includes the agent-runtime event stream,
summary-only'). Tails per-rung dialogues, distills SIGNAL events and appends to /tmp/agent_events.log,
which Vector auto-captures (/host-tmp/*.log). Primes to EOF so only NEW agent behaviour is emitted.
Usage: agent_stream.py [tick=8]"""
import glob, os, re, time, sys, json, collections
ROOT='/home/vmihaylov/java_8_11_17_to_java_21/current_attempt/per_repo_iter'
OUT='/tmp/agent_events.log'
STATE='/home/vmihaylov/java_8_11_17_to_java_21/current_attempt/telemetry/agent_stream.state.json'
PATS=[(re.compile(r'BAIL:([A-Z][A-Z0-9_]+)'),'BAIL'),
      (re.compile(r'\[ERROR\].{0,80}?(cannot find symbol|COMPILATION ERROR|BUILD FAILURE|Could not (?:find|resolve)[^\n]{0,50}|no POM in this directory)',re.I),'ERROR'),
      (re.compile(r'(NoSuchFieldError|NoClassDefFound|ClassNotFound|invalid (?:source|target) release|is a preview feature|Unsupported class file major version)'),'ERROR'),
      (re.compile(r'Auto Conversation Condensation|Condensation ──'),'CONDENSE'),
      (re.compile(r'reached maximum iterations'),'MAXITER'),
      (re.compile(r'=== DONE wall=|FINISH: \{|stop, you are done'),'DONE')]
TOOLCMD=re.compile(r'(?:tool_call: execute_bash\(\{"cmd": "|^\$ )(.{0,70})')
def main():
    tick=int(sys.argv[1]) if len(sys.argv)>1 else 8
    off={}
    if os.path.exists(STATE):
        try: off=json.load(open(STATE))
        except Exception: off={}
    primed=bool(off)
    out=open(OUT,'a')
    recent=collections.defaultdict(lambda: collections.deque(maxlen=8))
    while True:
        for p in glob.glob(f'{ROOT}/*/dialogue.*.log'):
            try: sz=os.path.getsize(p)
            except Exception: continue
            o=off.get(p)
            if o is None:
                off[p]= sz if not primed else 0  # first-ever sighting after priming starts at EOF only on cold start
                if not primed: continue
                o=0
            if o>sz: o=0
            if o>=sz: continue
            m=re.search(r'/([^/]+)/dialogue\.([a-z_]+)\.log$',p)
            slug=m.group(1) if m else '?'; rung=m.group(2) if m else '?'
            try:
                with open(p,'r',errors='replace') as f: f.seek(o); chunk=f.read(); off[p]=f.tell()
            except Exception: continue
            for ln in chunk.splitlines():
                hit=False
                for rx,kind in PATS:
                    mm=rx.search(ln)
                    if mm:
                        det=(mm.group(1) if mm.groups() else '')[:70]
                        out.write(f'{time.strftime("%H:%M:%S")} AGENT {slug} {rung} {kind} {det}\n'); out.flush(); hit=True; break
                if hit: continue
                tc=TOOLCMD.search(ln)
                if tc:
                    cmd=re.sub(r'\s+',' ',tc.group(1)).strip()[:50]; key=(slug,rung); recent[key].append(cmd)
                    if cmd and list(recent[key]).count(cmd)>=4:
                        out.write(f'{time.strftime("%H:%M:%S")} AGENT {slug} {rung} LOOP {cmd}\n'); out.flush(); recent[key].clear()
        primed=True
        json.dump(off,open(STATE,'w'))
        time.sleep(tick)
if __name__=='__main__': main()

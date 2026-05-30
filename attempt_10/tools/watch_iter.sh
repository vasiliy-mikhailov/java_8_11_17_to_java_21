#!/bin/bash
cd /home/vmihaylov/java_8_11_17_to_java_21/attempt_10
python3 -c "
import json,collections
rows=[json.loads(l) for l in open('feedback_p3_iter.jsonl')]
agg=collections.defaultdict(collections.Counter); st=collections.defaultdict(dict)
for d in rows: agg[d['rung']][d['outcome'].split(':')[0]]+=1; st[d['stage']][d['rung']]=d['outcome']
done=sum(1 for s,r in st.items() if {'opus','qwen','oh_qwen'}<=set(r.keys()))
print('done=%d | opus %s | qwen %s | oh %s'%(done,dict(agg['opus']),dict(agg['qwen']),dict(agg['oh_qwen'])))
for s,r in st.items():
  q=r.get(\"qwen\",\"PASS\"); o=r.get(\"oh_qwen\",\"PASS\")
  if q[:4]!=\"PASS\" or o[:4]!=\"PASS\": print(\"  AGENTFAIL\",s,\"qwen=%s oh=%s\"%(r.get(\"qwen\",\"-\"),r.get(\"oh_qwen\",\"-\")))
"
echo "mgr: launched=$(grep -c launch /tmp/ladder_continuous.log) finished=$(grep -c finished /tmp/ladder_continuous.log) inflight=$(pgrep -f "bash .*ladder_one.sh"|wc -l) | $(uptime|grep -oE "load average: .*")"

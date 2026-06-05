#!/usr/bin/env python3
'''Promote verified test-green J8/J11 baselines into the dataset.
Appends /tmp/verify_green.jsonl baselines to dataset-shas.json (dedup by repo+sha)
and any brand-new repos to dataset-repos.json. Reports the rebalanced hop counts.'''
import json
from collections import Counter
A='/home/vmihaylov/java_8_11_17_to_java_21/current_attempt'
green=[json.loads(l) for l in open('/tmp/verify_green.jsonl') if l.strip()]
shas=json.load(open(A+'/dataset-shas.json'))
have={(d['repo'],d['sha']) for d in shas}
added=0
for g in green:
    if (g['repo'],g['sha']) not in have:
        shas.append({'repo':g['repo'],'sha':g['sha'],'jv_from':g['jv_from'],'jv_to':g['jv_to'],'baseline_tests_pass':True})
        have.add((g['repo'],g['sha'])); added+=1
json.dump(shas, open(A+'/dataset-shas.json','w'), indent=1)
repos=json.load(open(A+'/dataset-repos.json')); rset=set(repos); newr=0
for g in green:
    if g['repo'] not in rset: repos.append(g['repo']); rset.add(g['repo']); newr+=1
json.dump(repos, open(A+'/dataset-repos.json','w'), indent=1)
print('promoted %d green baselines (+%d brand-new repos)'%(added,newr))
print('dataset-shas.json now %d datapoints; hops=%s'%(len(shas),dict(Counter('%d->%d'%(d['jv_from'],d['jv_to']) for d in shas))))

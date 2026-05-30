#!/bin/bash
set -u
T=/home/vmihaylov/java_8_11_17_to_java_21/attempt_10
SLUG="$1"; REPO="$2"; SHA="$3"; JF="$4"; JT="$5"
OUT="$T/per_repo_iter/val_${SLUG}"; mkdir -p "$OUT"; WD="/tmp/val_${SLUG}.oh"
rm -rf "$WD"; git clone -q --depth 120 "https://github.com/$REPO" "$WD" && ( cd "$WD" && git fetch -q --depth 240 origin "$SHA" && git checkout -q "$SHA" )
( cd /tmp && PATH=$HOME/bin:/tmp:$PATH timeout 620 python3 /tmp/oh_one.py "$WD" "val_${SLUG}" >"$OUT/dialogue.oh_qwen.log" 2>&1 )
python3 -c "
import sys; sys.path.insert(0,'$T/tools'); import d10_outer_persist as d
post=d.surefire_counts('$WD'); pom=d.pom_java_version('$WD')
ok = pom=='$JT' and post['failures']+post['errors']==0 and post['tests']>=1
print('VALIDATION ${SLUG} -> ' + ('PASS' if ok else 'STILL-FAILING') + f' (pom={pom} tests={post[\"tests\"]} fail={post[\"failures\"]} err={post[\"errors\"]})')
" | tee "$OUT/verdict.txt"

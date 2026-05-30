#!/bin/bash
# Re-run ONE failed datapoint's OH rung with the current (fixed) prompt + verdict; append corrected feedback row.
set -u
T=/home/vmihaylov/java_8_11_17_to_java_21/attempt_10
SLUG="$1"; REPO="$2"; SHA="$3"
OUT="$T/per_repo_iter/$SLUG"; WD="/tmp/rr_${SLUG}.oh"; FB="$T/feedback_p3_iter.jsonl"
mkdir -p "$OUT"; rm -rf "$WD"
git clone -q --depth 120 "https://github.com/$REPO" "$WD" && ( cd "$WD" && git fetch -q --depth 240 origin "$SHA" && git checkout -q "$SHA" )
( cd /tmp && PATH=$HOME/bin:/tmp:$PATH timeout 1500 python3 /tmp/oh_one.py "$WD" "$SLUG" >"$OUT/dialogue.oh_qwen.log" 2>&1 )
python3 - "$WD" "$OUT" "$SLUG" "$FB" << "PYX"
import sys, json, os, time
sys.path.insert(0,"/home/vmihaylov/java_8_11_17_to_java_21/attempt_10/tools"); import d10_outer_persist as d
wd,out,slug,fb=sys.argv[1:5]
pre=json.load(open(f"{out}/pre.json")) if os.path.exists(f"{out}/pre.json") else None
post=d.surefire_counts(wd); pom=d.pom_java_version(wd)
v=d.compute_verdict(pom,21,pre,post,f"{out}/dialogue.oh_qwen.log")
open(fb,"a").write(json.dumps({"ts":time.strftime("%Y-%m-%dT%H:%M:%S"),"stage":slug,"rung":"oh_qwen","prompt_sha":"7f8406ce11fe","recipe_catalog_sha":"e9d533fecf22","outcome":v,"rerun":True})+"\n")
print(f"RERUN {slug} -> {v} pom={pom}")
PYX
docker run --rm -v /tmp:/t busybox sh -c "rm -rf /t/rr_${SLUG}.oh" >/dev/null 2>&1

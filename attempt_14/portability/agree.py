#!/usr/bin/env python3
import json, glob, os
agents = ["opencode", "kilo", "openhands"]
data = {}
for a in agents:
    for d in glob.glob("/home/vmihaylov/sweep3_%s/*/" % a):
        rp = d + "result.json"
        if not os.path.exists(rp):
            continue
        r = json.load(open(rp))
        key = r["repo"] + " [" + r["hop"] + "]"
        data.setdefault(key, {})[a] = r["verdict"]
print("%-50s %-11s %-11s %-11s" % ("repo", "opencode", "kilo", "openhands"))
for repo in sorted(data):
    v = data[repo]
    cells = "  ".join("%-10s" % (v.get(a, "-")[:10]) for a in agents)
    verds = set(v.get(a) for a in agents)
    flag = ""
    if len(verds) > 1:
        flag = "   <-- DISAGREE"
    elif "PASS" not in verds:
        flag = "   <-- all FAIL"
    print("%-50s %s%s" % (repo[:50], cells, flag))

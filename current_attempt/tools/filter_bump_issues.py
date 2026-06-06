#!/usr/bin/env python3
import json, re
rows = json.load(open("/home/vmihaylov/bump_issues.json"))
good = re.compile(r"(upgrade|migrat|update|move|bump).{0,25}(to\s+)?(java|jdk)\s*\d{1,2}\b"
                  r"|(java|jdk)\s*\d{1,2}\b.{0,20}(upgrade|support|migration)"
                  r"|upgrade java version|latest lts version", re.I)
bad = re.compile(r"connector|mysql|\.time|jzlib|\basm\b|codegen|driver|-java\b|javassist|javaparser|javadoc|deflate",
                 re.I)
clean = [r for r in rows if good.search(r["title"]) and not bad.search(r["title"])]
print("%d clean JDK-version-bump requests (of %d total)\n" % (len(clean), len(rows)))
for r in clean[:30]:
    print("  %-40s %s" % (r["repo"], r["title"][:52]))
    print("        %s  (%s)" % (r["url"], r["created"]))
json.dump(clean, open("/home/vmihaylov/bump_issues_clean.json", "w"), indent=1)
print("\n-> /home/vmihaylov/bump_issues_clean.json (%d repos)" % len(clean))

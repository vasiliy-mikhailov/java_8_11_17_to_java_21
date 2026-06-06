#!/usr/bin/env python3
"""Rung-1 batch triage: cluster failed datapoints by root-cause signature, so each distinct
problem gets ONE deterministic fix (script/recipe) rather than per-datapoint rows that the
production agent won't apply. Reads sweep_results.json + per_repo_iter/<slug>/logs/test_post.log.
Usage: rung1_triage.py [results.json]"""
import json, os, re, sys, collections

ACTIVE = "/home/vmihaylov/java_8_11_17_to_java_21/current_attempt"
RES = sys.argv[1] if len(sys.argv) > 1 else ACTIVE + "/sweep_results.json"
OUT = ACTIVE + "/per_repo_iter"

# ordered: first match wins (specific -> generic)
KNOWN = [
    ("recipe-not-found (multi-module configLocation)", r"Recipe\(s\) not found"),
    ("version-parse lib (ArrayIndexOOB in <clinit>)", r"ArrayIndexOutOfBoundsException: Index 1 out of bounds for length 1"),
    ("tools.jar / com.sun:tools removed JDK9+", r"com\.sun:tools|/lib/tools\.jar"),
    ("SB2-BOM byte-buddy / ASM (major version 65)", r"major version 6[0-9]|Byte ?Buddy|ASM ClassReader"),
    ("Spring Boot 1.x / Spring 4.x too old", r"spring-boot-1\.|spring-context-4\.|EmbeddedServletContainerException"),
    ("Spring Security 6 WSCA removed", r"WebSecurityConfigurerAdapter"),
    ("Bean Validation provider missing", r"no Bean Validation provider"),
    ("javax.* removed (jaxb/annotation/activation)", r"package javax\.(xml\.bind|annotation|activation|jws|xml\.ws)"),
    ("HttpStatus -> HttpStatusCode (Spring 6)", r"HttpStatusCode cannot be converted"),
    ("UpgradeBuildToJava17 (build17) recipe fail", r"UpgradeBuildToJava17"),
    ("Docker/Selenium env (not a regression)", r"valid Docker environment|Previous attempts to find a Docker|selenium"),
    ("dependency resolution (artifact gone)", r"Could not (resolve dependencies|find artifact)|Failure to find|Could not transfer"),
    ("source/target / enable-preview", r"invalid (source|target) release|enable-preview|release version \d+ not supported"),
]


def signature(slug):
    log = ""
    for n in ("logs/test_post.log", "logs/compile_post.log"):
        p = f"{OUT}/{slug}/{n}"
        if os.path.exists(p):
            try:
                log = open(p, errors="replace").read()
                break
            except Exception:
                pass
    if not log:
        return "(no log / harness)", ""
    for name, pat in KNOWN:
        m = re.search(pat, log)
        if m:
            for line in log.splitlines():
                if re.search(pat, line) and not re.search(r"Help 1|Re-run|cwiki", line):
                    return name, line.strip()[:150]
            return name, ""
    cm = re.search(r"(cannot find symbol|package [\w.]+ does not exist|COMPILATION ERROR)", log)
    if cm:
        for line in log.splitlines():
            if cm.group(0) in line and ".java:" in line:
                return "compile: " + cm.group(1), line.strip()[:150]
        return "compile: " + cm.group(1), ""
    cb = [l for l in log.splitlines() if "Caused by:" in l]
    if cb:
        ex = re.search(r"Caused by:\s*([\w.]+(?:Exception|Error))", cb[-1])
        return "test-exc: " + (ex.group(1).split(".")[-1] if ex else "exception"), cb[-1].strip()[:150]
    return "other/novel", ""


def main():
    res = json.load(open(RES))
    fails = {k: v for k, v in res.items()
             if isinstance(v, str) and (v.startswith("FAIL") or v == "TIMEOUT" or v.startswith("rc="))}
    clusters = collections.defaultdict(list)
    samples = {}
    hops = {}
    try:
        ds = {(x["repo"].replace("/", "_") + "_" + x["sha"][:12]): "%d->%d" % (x["jv_from"], x["jv_to"])
              for x in json.load(open(ACTIVE + "/dataset-shas.json"))}
    except Exception:
        ds = {}
    for slug, v in fails.items():
        s, sample = signature(slug)
        clusters[s].append(slug)
        samples.setdefault(s, sample)
        hops.setdefault(s, collections.Counter())[ds.get(slug, "?")] += 1
    print("=== rung-1 batch triage: %d failures -> %d root-cause clusters ===\n" % (len(fails), len(clusters)))
    for s in sorted(clusters, key=lambda x: -len(clusters[x])):
        print("[%2d] %-46s hops=%s" % (len(clusters[s]), s, dict(hops[s])))
        if samples[s]:
            print("       e.g. %s" % samples[s])
    json.dump({s: clusters[s] for s in clusters}, open("/tmp/fail_clusters.json", "w"))
    print("\nwrote /tmp/fail_clusters.json")


if __name__ == "__main__":
    main()

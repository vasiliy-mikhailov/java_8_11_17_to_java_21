"""ff #1 test-conservation criterion.

For a recipe chain to PASS under the stronger criterion (next-iteration scope):
  1. All steps' recipe-apply succeed (rc=0), AND
  2. All steps' mvn compile succeed (rc=0), AND
  3. Every (test class, test method) tuple that PASSED in test_pre (mvn test on
     the unmodified clone under jv_from) must still PASS in test_post (mvn test
     on the post-recipe tree under jv_to).

Tests that were already failing pre-recipe don't count against the recipe;
breaking a previously-passing test is a FAIL.

Usage:
  from test_conservation import run_test_phase, check_test_conservation
"""
import os, glob, xml.etree.ElementTree as ET


def parse_surefire_dir(work_dir):
    """Walk target/surefire-reports/ across all modules. Returns (passed, failed) sets of (class, method)."""
    passed = set()
    failed = set()
    for xml_path in glob.glob(f"{work_dir}/**/target/surefire-reports/TEST-*.xml", recursive=True):
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            for tc in root.findall("testcase"):
                cls = tc.get("classname"); name = tc.get("name")
                if cls is None or name is None:
                    continue
                tup = (cls, name)
                if tc.find("failure") is not None or tc.find("error") is not None:
                    failed.add(tup)
                elif tc.find("skipped") is not None:
                    continue  # don't count skipped either way
                else:
                    passed.add(tup)
        except ET.ParseError:
            continue
    return passed, failed


def clear_surefire(work_dir):
    """Delete prior surefire-reports so test_pre and test_post don't share state."""
    import shutil
    for d in glob.glob(f"{work_dir}/**/target/surefire-reports", recursive=True):
        shutil.rmtree(d, ignore_errors=True)


def check_test_conservation(pre_passed, post_passed):
    """Returns (ok, regressed_tuples)."""
    regressed = sorted(pre_passed - post_passed)
    return len(regressed) == 0, regressed


def fmt_regression(regressed, limit=20):
    """Compact human-readable form of regressed tests (for Qwen + logs)."""
    out = []
    for cls, name in regressed[:limit]:
        out.append(f"  - {cls}.{name}")
    if len(regressed) > limit:
        out.append(f"  ... +{len(regressed) - limit} more")
    return "\n".join(out)


if __name__ == "__main__":
    # smoke: parse a given work dir
    import sys, json
    if len(sys.argv) < 2:
        print("usage: test_conservation.py <work_dir>")
        sys.exit(1)
    p, f = parse_surefire_dir(sys.argv[1])
    print(json.dumps({
        "passed_count": len(p), "failed_count": len(f),
        "passed_sample": [f"{c}.{n}" for c, n in sorted(p)[:5]],
        "failed_sample": [f"{c}.{n}" for c, n in sorted(f)[:5]],
    }, indent=2))

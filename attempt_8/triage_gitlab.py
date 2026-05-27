#!/usr/bin/env python3
"""
triage_gitlab.py — discover Java projects in a GitLab group and emit one
machine-consumable triage JSON record per project. Output feeds the
deterministic chain composer that decides which projects get converted to
Java 21 with which chain.

Pure Python + GitLab REST API. No LLM. No clone. One project archive download
per repo, parsed and grepped locally.

═══════════════════════════════════════════════════════════════════════════════
USAGE
═══════════════════════════════════════════════════════════════════════════════

  triage_gitlab.py --group <id-or-path> [--output-dir DIR] [--limit N] [--resume]

Required env vars:
    GITLAB_URL    e.g. https://gitlab.example.com  (or https://gitlab.com)
    GITLAB_TOKEN  Personal Access Token with 'read_api' + 'read_repository' scope

Examples:
    GITLAB_URL=https://gitlab.com GITLAB_TOKEN=glpat-...  \
        triage_gitlab.py --group my-org/backend --output-dir ./triage

    triage_gitlab.py --group 1234 --output-dir ./triage --limit 5

Resume: re-running on the same --output-dir skips projects whose triage
JSON is already present. Pass --no-resume to force re-triage.

═══════════════════════════════════════════════════════════════════════════════
OUTPUT
═══════════════════════════════════════════════════════════════════════════════

Per project:
    <output-dir>/<project_path_with_slashes_replaced>.json

Plus a corpus summary at:
    <output-dir>/_summary.json

═══════════════════════════════════════════════════════════════════════════════
DEPENDENCIES — only requests, stdlib-only otherwise
═══════════════════════════════════════════════════════════════════════════════

    pip install requests

═══════════════════════════════════════════════════════════════════════════════
WHAT THIS CHECKS PER PROJECT
═══════════════════════════════════════════════════════════════════════════════

  - Build tool (maven / gradle / ant / other / none)
  - Multi-module yes/no
  - Java version declared (from pom or gradle)
  - Spring Boot version (from parent or BOM)
  - Primary language (java / kotlin / scala / groovy)
  - Frameworks present (from a fixed vocabulary, detected via deps + imports)
  - Code signals (javax.xml.bind, WebSecurityConfigurerAdapter, @Type(type=...),
    @MockBean, --enable-preview, aspectj-maven-plugin, hibernate-jpamodelgen,
    frontend-maven-plugin, jakarta.xml.bind)
  - Approximate counts (modules, source files, test files)
  - Blockers (non-maven, kotlin-primary, springfox-present, etc.)

═══════════════════════════════════════════════════════════════════════════════
"""
import os, sys, json, re, argparse, time, tarfile, tempfile, shutil
from pathlib import Path
from urllib.parse import quote
import requests

# ═══ vocabularies (kept here, not in AGENTS.md, so they can change freely) ════

FRAMEWORK_VOCAB = {
    'spring-boot':     [r'spring-boot-starter-', r'spring-boot-dependencies'],
    'spring-security': [r'spring-security-', r'org\.springframework\.security'],
    'spring-cloud':    [r'spring-cloud-'],
    'hibernate':       [r'hibernate-core', r'hibernate-orm', r'org\.hibernate\.'],
    'jpa':             [r'javax\.persistence\.', r'jakarta\.persistence\.'],
    'jakarta-ee':      [r'jakarta\.[a-z]+\.'],
    'springfox':       [r'io\.springfox', r'springfox\.documentation'],
    'springdoc':       [r'springdoc-openapi'],
    'jhipster':        [r'io\.github\.jhipster:jhipster'],
    'quarkus':         [r'io\.quarkus:'],
    'micronaut':       [r'io\.micronaut:'],
    'mapstruct':       [r'org\.mapstruct:', r'@org\.mapstruct\.Mapper', r'@Mapper'],
    'lombok':          [r'org\.projectlombok:lombok', r'import lombok\.'],
    'junit4':          [r'junit:junit:4', r'import org\.junit\.Test;'],
    'junit5':          [r'junit-jupiter', r'org\.junit\.jupiter'],
    'mockito':         [r'mockito-core', r'mockito-junit-jupiter'],
    'testng':          [r'org\.testng:', r'import org\.testng\.'],
    'assertj':         [r'assertj-core'],
}

CODE_SIGNAL_PATTERNS = {
    'uses_javax_xml_bind':                  ('src/main', r'import\s+javax\.xml\.bind\.'),
    'uses_jakarta_xml_bind':                ('src/main', r'import\s+jakarta\.xml\.bind\.'),
    'uses_web_security_configurer_adapter': ('src/main', r'extends\s+WebSecurityConfigurerAdapter'),
    'uses_hibernate5_type_syntax':          ('src/main', r'@Type\s*\(\s*type\s*=\s*"'),
    'uses_mockbean':                        ('src/test', r'@MockBean'),
    'uses_enable_preview':                  ('__pom__', r'--enable-preview'),
    'uses_aspectj_plugin':                  ('__pom__', r'aspectj-maven-plugin'),
    'uses_jpamodelgen':                     ('__pom__', r'hibernate-jpamodelgen'),
    'uses_frontend_maven_plugin':           ('__pom__', r'frontend-maven-plugin'),
}

BLOCKER_RULES = [
    ('non-maven',         lambda r: r['build_tool'] in ('gradle', 'ant', 'other')),
    ('kotlin-primary',    lambda r: r['primary_language'] == 'kotlin'),
    ('scala-primary',     lambda r: r['primary_language'] == 'scala'),
    ('groovy-primary',    lambda r: r['primary_language'] == 'groovy'),
    ('springfox-present', lambda r: 'springfox' in r['frameworks']),
    ('no-source',         lambda r: r['is_java_project'] and r.get('approx_source_file_count', 0) == 0),
    ('broken-pom',        lambda r: r.get('_broken_pom', False)),
]

# ═══ GitLab API client ════════════════════════════════════════════════════════

class GitLab:
    def __init__(self, base_url, token):
        self.base = base_url.rstrip('/') + '/api/v4'
        self.s = requests.Session()
        self.s.headers.update({'PRIVATE-TOKEN': token})

    def _get(self, path, **params):
        r = self.s.get(self.base + path, params=params, timeout=30)
        r.raise_for_status()
        return r

    def list_group_projects(self, group):
        '''Return all projects in a group, including subgroups. Paginated.'''
        gid = quote(str(group), safe='')
        projects, page = [], 1
        while True:
            r = self._get(f'/groups/{gid}/projects',
                          include_subgroups='true', per_page=100, page=page,
                          archived='false', simple='false')
            batch = r.json()
            if not batch: break
            projects.extend(batch)
            if 'next' not in r.headers.get('Link', ''): break
            page += 1
            time.sleep(0.2)
        return projects

    def download_archive(self, project_id, ref, dst_path):
        '''Download project archive (tar.gz) to dst_path.'''
        url = f'{self.base}/projects/{project_id}/repository/archive.tar.gz'
        r = self.s.get(url, params={'sha': ref}, timeout=120, stream=True)
        r.raise_for_status()
        with open(dst_path, 'wb') as f:
            for chunk in r.iter_content(65536):
                f.write(chunk)


# ═══ per-project triage ═══════════════════════════════════════════════════════

def grep_recursive(root, pattern_re, subdir=None):
    '''Return True if any file under root (or root/subdir) matches the regex.'''
    base = root / subdir if subdir else root
    if not base.exists(): return None  # not observable
    rx = re.compile(pattern_re)
    for dirpath, _, files in os.walk(base):
        for f in files:
            if not f.endswith(('.java', '.kt', '.scala', '.groovy', '.xml', '.gradle', '.kts')):
                continue
            try:
                with open(Path(dirpath)/f, errors='replace') as fh:
                    if rx.search(fh.read()):
                        return True
            except (OSError, UnicodeError):
                continue
    return False


def parse_pom(pom_path):
    '''Extract key facts from pom.xml without full XML parsing — string-grep
    is good enough for the signals we want and avoids xml.etree quirks.'''
    try:
        s = pom_path.read_text(errors='replace')
    except OSError:
        return {'_broken_pom': True}
    out = {}
    # java version: take largest match
    versions = re.findall(r'<(?:java\.version|maven\.compiler\.(?:source|target|release))>'
                          r'\s*([\d.]+)\s*<', s)
    versions = [v.lstrip('1.') if v.startswith('1.') else v for v in versions if v]
    if versions:
        out['java_version_declared'] = max(versions, key=lambda v: int(v.split('.')[0]))
    # spring-boot version
    sb = re.search(r'<artifactId>spring-boot-(?:starter-)?(?:parent|dependencies)</artifactId>\s*'
                   r'<version>([^<]+)</version>', s)
    out['spring_boot_version'] = sb.group(1) if sb else None
    # modules
    out['modules'] = re.findall(r'<module>([^<]+)</module>', s)
    out['_pom_text'] = s
    return out


def detect_frameworks(pom_texts_joined, src_root):
    '''Match framework vocabulary against pom XML AND deduplicated source imports.'''
    haystack = pom_texts_joined
    # Plus all imports from src/main/java
    if src_root.exists():
        for dirpath, _, files in os.walk(src_root):
            for f in files:
                if f.endswith('.java') or f.endswith('.kt'):
                    try:
                        with open(Path(dirpath)/f, errors='replace') as fh:
                            for line in fh:
                                if line.startswith('import ') or line.startswith('package '):
                                    haystack += '\n' + line
                                elif not line.startswith(('//', '/*', ' ', '\t')):
                                    break  # past header
                    except OSError:
                        continue
    found = []
    for fw, patterns in FRAMEWORK_VOCAB.items():
        if any(re.search(p, haystack) for p in patterns):
            found.append(fw)
    return sorted(found)


def primary_language(repo_root):
    counts = {'java': 0, 'kotlin': 0, 'scala': 0, 'groovy': 0}
    src = repo_root / 'src' / 'main'
    if not src.exists():
        # try a flat layout: any *.java/.kt anywhere
        src = repo_root
    for dirpath, _, files in os.walk(src):
        for f in files:
            if f.endswith('.java'):   counts['java'] += 1
            elif f.endswith('.kt'):   counts['kotlin'] += 1
            elif f.endswith('.scala'): counts['scala'] += 1
            elif f.endswith('.groovy'): counts['groovy'] += 1
    total = sum(counts.values())
    if total == 0: return None
    leader = max(counts.items(), key=lambda kv: kv[1])
    if leader[1] / total >= 0.7: return leader[0]
    return 'mixed'


def count_files(repo_root, subdir, exts):
    base = repo_root / subdir
    if not base.exists(): return None
    n = 0
    for dirpath, _, files in os.walk(base):
        for f in files:
            if any(f.endswith(e) for e in exts):
                n += 1
    return n


def triage_one(repo_root):
    '''Build the JSON record from an extracted project tree.'''
    rec = {'is_java_project': False}
    has_pom = (repo_root / 'pom.xml').exists()
    has_gradle = any((repo_root / n).exists() for n in ('build.gradle','build.gradle.kts'))
    has_ant = (repo_root / 'build.xml').exists()
    any_java_src = primary_language(repo_root) is not None
    rec['is_java_project'] = has_pom or has_gradle or has_ant or any_java_src

    if has_pom:       rec['build_tool'] = 'maven'
    elif has_gradle:  rec['build_tool'] = 'gradle'
    elif has_ant:     rec['build_tool'] = 'ant'
    elif any_java_src: rec['build_tool'] = 'other'
    else:              rec['build_tool'] = 'none'

    rec['primary_language'] = primary_language(repo_root)

    pom_data = {}
    pom_texts = ''
    if has_pom:
        pom_data = parse_pom(repo_root / 'pom.xml')
        pom_texts = pom_data.get('_pom_text', '')
        # walk submodule poms too
        for sub in pom_data.get('modules', []):
            sp = repo_root / sub / 'pom.xml'
            if sp.exists():
                sub_data = parse_pom(sp)
                pom_texts += '\n' + sub_data.get('_pom_text', '')

    rec['is_multi_module'] = (len(pom_data.get('modules', [])) > 0) if has_pom else (False if has_gradle else None)
    rec['java_version_declared'] = pom_data.get('java_version_declared')
    rec['spring_boot_version'] = pom_data.get('spring_boot_version')

    rec['frameworks'] = detect_frameworks(pom_texts, repo_root / 'src' / 'main')

    # code signals
    signals = {}
    for name, (where, pat) in CODE_SIGNAL_PATTERNS.items():
        if where == '__pom__':
            signals[name] = bool(re.search(pat, pom_texts)) if has_pom else None
        else:
            signals[name] = grep_recursive(repo_root, pat, subdir=where)
    rec['code_signals'] = signals

    # counts
    rec['approx_module_count'] = (
        1 + len(pom_data.get('modules', [])) if has_pom else None)
    rec['approx_source_file_count'] = count_files(repo_root, 'src/main', ('.java', '.kt'))
    if rec['approx_source_file_count'] is None:
        # flat layout fallback
        n = 0
        for dirpath, _, files in os.walk(repo_root):
            n += sum(1 for f in files if f.endswith(('.java', '.kt'))
                     and 'test' not in dirpath.lower())
            if n > 5000: break
        rec['approx_source_file_count'] = n
    rec['approx_test_file_count'] = count_files(repo_root, 'src/test', ('.java', '.kt'))

    rec['_broken_pom'] = pom_data.get('_broken_pom', False)

    # blockers
    rec['blockers'] = sorted({tag for tag, fn in BLOCKER_RULES if fn(rec)})

    # if NOT a java project, null out all code signals
    if not rec['is_java_project']:
        rec['code_signals'] = {k: None for k in rec['code_signals']}

    rec['notes'] = ''
    rec.pop('_broken_pom', None)
    return rec


# ═══ orchestration ════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter,
                                 description=__doc__)
    ap.add_argument('--group', required=True, help='GitLab group ID or path (e.g. "my-org/backend")')
    ap.add_argument('--output-dir', default='./triage', help='Where to write per-project JSON')
    ap.add_argument('--limit', type=int, default=0, help='Triage only the first N projects (0 = all)')
    ap.add_argument('--resume', action='store_true', default=True, help='Skip projects with existing JSON (default)')
    ap.add_argument('--no-resume', dest='resume', action='store_false', help='Re-triage even if JSON exists')
    args = ap.parse_args()

    base_url = os.environ.get('GITLAB_URL')
    token = os.environ.get('GITLAB_TOKEN')
    if not base_url or not token:
        print('error: set GITLAB_URL and GITLAB_TOKEN env vars', file=sys.stderr)
        return 2

    gl = GitLab(base_url, token)
    out_dir = Path(args.output_dir); out_dir.mkdir(parents=True, exist_ok=True)

    print(f'== discovering projects in group {args.group} ==', flush=True)
    projects = gl.list_group_projects(args.group)
    print(f'   found {len(projects)} project(s) (including subgroups)', flush=True)
    if args.limit: projects = projects[:args.limit]

    summary = {'total': 0, 'by_build_tool': {}, 'by_jv': {}, 'by_blocker': {}, 'java_projects': 0}
    for i, p in enumerate(projects, 1):
        slug = p['path_with_namespace'].replace('/', '__')
        out_path = out_dir / f'{slug}.json'
        if args.resume and out_path.exists():
            print(f'   [{i}/{len(projects)}] {slug}: cached, skip', flush=True)
            try: rec = json.loads(out_path.read_text())
            except: rec = None
        else:
            print(f'   [{i}/{len(projects)}] {slug}: fetching archive…', end='', flush=True)
            tmp = Path(tempfile.mkdtemp(prefix='triage_'))
            try:
                arc = tmp / 'r.tar.gz'
                gl.download_archive(p['id'], p.get('default_branch', 'main'), arc)
                with tarfile.open(arc) as tar:
                    tar.extractall(tmp, filter='data')
                # archive's top-level dir is usually <project>-<branch>-<sha>
                tops = [d for d in tmp.iterdir() if d.is_dir()]
                repo_root = tops[0] if tops else tmp
                rec = triage_one(repo_root)
                out_path.write_text(json.dumps(rec, indent=2, sort_keys=True))
                tag = ('FAIL' if not rec['is_java_project'] else
                       f"j{rec['java_version_declared']}/{rec['build_tool']}")
                print(f' {tag}', flush=True)
            except Exception as e:
                print(f' ERROR: {type(e).__name__}: {e}', flush=True)
                rec = {'is_java_project': False, 'notes': f'{type(e).__name__}: {e}'}
                out_path.write_text(json.dumps(rec, indent=2, sort_keys=True))
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        if rec:
            summary['total'] += 1
            if rec.get('is_java_project'): summary['java_projects'] += 1
            bt = rec.get('build_tool', 'unknown')
            summary['by_build_tool'][bt] = summary['by_build_tool'].get(bt, 0) + 1
            jv = rec.get('java_version_declared') or 'unknown'
            summary['by_jv'][jv] = summary['by_jv'].get(jv, 0) + 1
            for b in rec.get('blockers') or []:
                summary['by_blocker'][b] = summary['by_blocker'].get(b, 0) + 1

    (out_dir / '_summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True))
    print()
    print(f'== summary ==')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    sys.exit(main())

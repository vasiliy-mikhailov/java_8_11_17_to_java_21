import json, os, subprocess, tempfile, time, shutil, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict

HIST = json.load(open('attempt_2/verify/history_hits.json'))
CL   = json.load(open('attempt_2/verify/classified_v2.json'))

pool = defaultdict(list)
size_of = {r['full_name']: r.get('size_kb', 0) or 0 for r in CL}
mc_of   = {r['full_name']: r.get('module_count', 0) for r in CL}
for h in HIST:
    j = h['java_version']
    for fam in h['families_at_commit']:
        pool[(j, fam)].append({
            'java_version': j, 'family': fam,
            'repo_full_name': h['full_name'], 'owner': h['owner'], 'repo_name': h['repo'],
            'commit_sha': h['commit_sha'],
            'clone_url': f'https://github.com/{h["full_name"]}.git',
            'size_kb': size_of.get(h['full_name'], 0), 'module_count': mc_of.get(h['full_name'], 0),
            'source': 'history_walk',
        })
for r in CL:
    if r.get('java_version_declared') != 8: continue
    for fam in r.get('families_evidenced', []):
        pool[(8, fam)].append({
            'java_version': 8, 'family': fam,
            'repo_full_name': r['full_name'], 'owner': r['owner'], 'repo_name': r['repo'],
            'commit_sha': 'HEAD',
            'clone_url': f'https://github.com/{r["full_name"]}.git',
            'size_kb': r.get('size_kb', 0) or 0, 'module_count': r.get('module_count', 0),
            'source': 'classified_head',
        })
for k in list(pool):
    seen = set(); ordered = []
    for c in sorted(pool[k], key=lambda c: (c['module_count'], c['size_kb'] or 999999)):
        if c['owner'] in seen: continue
        seen.add(c['owner']); ordered.append(c)
    pool[k] = ordered

BASE_DIR = 'attempt_3/verify/baseline'
os.makedirs(BASE_DIR, exist_ok=True)
def safe(s, jv=None, fam=None):
    base = s.replace('/','__')
    if jv is not None and fam is not None: return f'{fam}__j{jv}__{base}'
    return base

def build_one(c):
    fn = c['repo_full_name']; sha = c['commit_sha']; jv = c['java_version']
    # Skip if already passed
    out_dir = os.path.join(BASE_DIR, safe(fn, jv, c.get('family')))
    m_path = os.path.join(out_dir, 'metrics.json')
    if os.path.exists(m_path):
        try:
            md = json.load(open(m_path))
            if md.get('build_pass'):
                return ('pass', {**c, 'commit_sha': md.get('commit_sha', sha), 'build_rc': 0, 'build_pass': True})
        except: pass
    out_dir = os.path.join(BASE_DIR, safe(fn, jv, c.get('family')))
    os.makedirs(out_dir, exist_ok=True)
    log_path = os.path.join(out_dir, 'run.log')
    src = tempfile.mkdtemp()
    try:
        with open(log_path, 'w') as L:
            L.write(f'== {fn} @ {sha} on Java {jv} ==\n'); L.flush()
            t0 = time.time()
            p = subprocess.run(['git','clone','--depth','1', c['clone_url'], src],
                               stdout=L, stderr=L, timeout=120)
            if p.returncode != 0:
                json.dump({'repo': fn, 'commit_sha': sha, 'java_version': jv,
                           'build_rc': -1, 'build_pass': False, 'error': 'clone_fail'},
                          open(os.path.join(out_dir,'metrics.json'),'w'), indent=2)
                return ('clone_fail', c)
            if sha and sha != 'HEAD':
                subprocess.run(['git','fetch','--depth','300','origin', sha], cwd=src,
                               stdout=L, stderr=L, timeout=120)
                subprocess.run(['git','checkout', sha], cwd=src, stdout=L, stderr=L, timeout=30)
            r = subprocess.run(['git','rev-parse','HEAD'], cwd=src, capture_output=True)
            actual_sha = r.stdout.decode().strip() if r.returncode==0 else 'UNKNOWN'
            root = src
            if not os.path.exists(os.path.join(src,'pom.xml')) and not os.path.exists(os.path.join(src,'build.gradle')) and not os.path.exists(os.path.join(src,'build.gradle.kts')):
                for r2,d,f in os.walk(src):
                    if 'pom.xml' in f:
                        root = r2; break
            build_tool = 'maven' if os.path.exists(os.path.join(root,'pom.xml')) else 'gradle'
            jdk_path = f'/opt/jdk/{jv}'
            mvn_flags = '-B -fae -Denforcer.skip=true -DskipTests -Dmaven.javadoc.skip=true -Dcheckstyle.skip=true -Dspotbugs.skip=true -Dspring-javaformat.skip=true -Dformat.skip=true'
            cmd = (f'if [ -f pom.xml ]; then mvn {mvn_flags} compile; '
                   f'else (./gradlew --no-daemon -x test compileJava 2>/dev/null || gradle --no-daemon -x test compileJava); fi')
            home = os.environ['HOME']
            docker_cmd = ['docker','run','--rm','--cpus','2.5','--memory','6g','--entrypoint','/bin/bash',
                          '-v', f'{root}:/work',
                          '-v', f'{home}/.m2-fitness:/root/.m2',
                          '-e', f'JAVA_HOME={jdk_path}',
                          '-e', f'PATH={jdk_path}/bin:/opt/maven/bin:/opt/gradle/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
                          '-w','/work','j21-fitness:latest','-c', cmd]
            t1 = time.time()
            try:
                p = subprocess.run(docker_cmd, stdout=L, stderr=L, timeout=600)
                rc = p.returncode
            except subprocess.TimeoutExpired:
                rc = 124
            build_elapsed = int(time.time() - t1); clone_elapsed = int(t1 - t0)
            metrics = {'repo': fn, 'commit_sha': actual_sha, 'java_version': jv,
                       'dep_family': c['family'], 'build_tool': build_tool,
                       'clone_elapsed_s': clone_elapsed, 'build_elapsed_s': build_elapsed,
                       'build_rc': rc, 'build_pass': (rc == 0)}
            json.dump(metrics, open(os.path.join(out_dir,'metrics.json'),'w'), indent=2)
            L.write(f'\n== DONE rc={rc} build={build_elapsed}s clone={clone_elapsed}s sha={actual_sha} ==\n')
            return ('pass' if rc==0 else 'build_fail', {**c, 'commit_sha': actual_sha, 'build_rc': rc, 'build_pass': rc==0})
    finally:
        shutil.rmtree(src, ignore_errors=True)

if __name__ == '__main__':
    final = []
    sem = threading.BoundedSemaphore(8)

    def cell_worker(cell, candidates):
        chosen = []
        for c in candidates:
            if len(chosen) >= 24: break
            with sem:
                status, info = build_one(c)
            if status == 'pass':
                chosen.append(info)
        return cell, chosen

    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(cell_worker, cell, cands[:80]): cell for cell, cands in pool.items()}
        for f in as_completed(futs):
            cell, chosen = f.result()
            print(f'{cell}: {len(chosen)} build_pass', flush=True)
            for i, c in enumerate(chosen, 1):
                final.append({'cell_id': f'{cell[1]}__j{cell[0]}__{i}', **c})

    json.dump(final, open('attempt_3/verify/baseline_summary.json','w'), indent=2)
    print(f'\nTotal build_pass: {len(final)}')


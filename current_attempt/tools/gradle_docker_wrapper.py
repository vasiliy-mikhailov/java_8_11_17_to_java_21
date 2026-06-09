#!/usr/bin/env python3
"""gradle wrapper — run every gradle invocation inside the j21-fitness container
(mirrors the mvn wrapper). JDK selectable via $JDK (default 21). Uses the repo's
own ./gradlew if present (correct Gradle version, bootstrapped from the net), else
the container's gradle. GRADLE_USER_HOME is a host-mounted cache so distributions
and deps are reused across repos. Runs as root; caller reaps root-owned build/."""
import os, sys
JDK   = os.environ.get('JDK', '21')
WORK  = os.environ.get('WORK_DIR', os.getcwd())
GHOME = os.environ.get('GRADLE_CACHE', '/home/vmihaylov/.gradle-fitness')
NET   = os.environ.get('MVN_NET', 'mvn-cache')
IMAGE = os.environ.get('IMAGE', 'j21-fitness:latest')
os.makedirs(GHOME, exist_ok=True)
INNER = (f'export HOME=/tmp; export JAVA_HOME=/opt/jdk/{JDK}; '
         f'export PATH="$JAVA_HOME/bin:/opt/gradle/bin:$PATH"; '
         f'export GRADLE_USER_HOME=/gradle-home; '
         f'git config --global --add safe.directory "*"; cd /work/src; '
         f'if [ -x ./gradlew ]; then exec ./gradlew --no-daemon "$@"; '
         f'else exec gradle --no-daemon "$@"; fi')
cmd = ['docker','run','--rm','--user','root',
       '-v', f'{WORK}:/work/src', '-v', f'{GHOME}:/gradle-home',
       '--network', NET, '-w','/work/src','--entrypoint','bash',
       IMAGE,'-c',INNER,'--', *sys.argv[1:]]
os.execvp(cmd[0], cmd)

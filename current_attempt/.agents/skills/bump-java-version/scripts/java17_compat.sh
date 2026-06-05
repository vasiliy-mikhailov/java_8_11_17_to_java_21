#!/bin/bash
# java17_compat.sh <workdir> — JDK 17/21 test-fork compat. Libraries like old Mockito-cglib,
# ByteBuddy, and various proxy/reflection frameworks call setAccessible on JDK-internal members
# (e.g. java.lang.ClassLoader.defineClass); JDK 16+ strongly encapsulates these, so the
# surefire-forked test JVM throws java.lang.reflect.InaccessibleObjectException. Inject the
# standard --add-opens set into the maven-surefire-plugin <argLine> so the test fork can run.
# Idempotent; scoped to the surefire plugin; preserves any existing <argLine> (e.g. jacoco).
set -uo pipefail
WORK=${1:?usage: java17_compat.sh <workdir>}; cd "$WORK"

python3 - <<'PY'
import glob, re
OPENS=("--add-opens java.base/java.lang=ALL-UNNAMED "
       "--add-opens java.base/java.lang.reflect=ALL-UNNAMED "
       "--add-opens java.base/java.util=ALL-UNNAMED "
       "--add-opens java.base/java.text=ALL-UNNAMED "
       "--add-opens java.base/java.io=ALL-UNNAMED "
       "--add-opens java.base/java.nio=ALL-UNNAMED "
       "--add-opens java.base/java.time=ALL-UNNAMED "
       "--add-opens java.base/sun.nio.ch=ALL-UNNAMED "
       "--add-opens java.desktop/java.awt.font=ALL-UNNAMED "
       "--add-opens java.management/java.lang.management=ALL-UNNAMED")
MARK="<!--jdk17-add-opens-->"
# Target the shallowest (root/parent) pom; surefire config in a parent <build><plugins> is
# inherited by child modules, so the whole reactor's forks get the opens.
poms=sorted(set(glob.glob("pom.xml")+glob.glob("*/pom.xml")+glob.glob("*/*/pom.xml")), key=len)
root=poms[0] if poms else None
if root:
    s=open(root).read()
    if MARK in s:
        print("add-opens already present in "+root)
    else:
        # locate the maven-surefire-plugin <plugin> element (don't cross plugin boundaries)
        m=re.search(r"<plugin>(?:(?!</plugin>).)*?<artifactId>maven-surefire-plugin</artifactId>(?:(?!</plugin>).)*?</plugin>", s, flags=re.S)
        ins=MARK+OPENS
        if m:
            blk=m.group(0)
            if "<argLine>" in blk:                       # append, preserving existing (e.g. @{argLine} jacoco)
                newblk=re.sub(r"<argLine>", "<argLine>"+ins+" ", blk, count=1)
            elif "<configuration>" in blk:
                newblk=blk.replace("<configuration>","<configuration><argLine>"+ins+"</argLine>",1)
            else:
                newblk=blk.replace("</plugin>","<configuration><argLine>"+ins+"</argLine></configuration></plugin>",1)
            s=s.replace(blk,newblk,1)
        else:
            plug=("<plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId>"
                  "<configuration><argLine>"+ins+"</argLine></configuration></plugin>")
            if "<plugins>" in s: s=s.replace("<plugins>","<plugins>"+plug,1)
            elif "<build>" in s: s=s.replace("<build>","<build><plugins>"+plug+"</plugins>",1)
            else: s=s.replace("</project>","<build><plugins>"+plug+"</plugins></build></project>",1)
        open(root,"w").write(s); print("surefire --add-opens injected into "+root)
PY
# JaCoCo's bundled ASM can't read Java 17/21 bytecode (java.lang.IllegalArgumentException:
# Unsupported class file major version 61/65 at org.jacoco...asm.ClassReader). Bump the pinned
# jacoco-maven-plugin to 0.8.12 (reads JDK 8..21). Only fires if jacoco is pinned at an old version.
echo "=== [jacoco_compat] bumping old JaCoCo (if pinned) to JDK17/21-aware 0.8.12" >&2
python3 - <<'PY'
import glob, re
NEW="0.8.12"
poms=sorted(set(glob.glob("pom.xml")+glob.glob("*/pom.xml")+glob.glob("*/*/pom.xml")), key=len)
for p in poms:
    s=open(p).read(); orig=s
    # property form: <jacoco.version>0.8.5</...>, <jacoco-maven-plugin.version>..</..>, <jacoco-maven.version>..</..>
    s=re.sub(r"(<jacoco[a-z.-]*\.version>)\s*0\.(?:7\.[0-9]+|8\.(?:[0-9]|1[01])(?:\.[0-9]+)?)\s*(</jacoco[a-z.-]*\.version>)",
             r"\g<1>"+NEW+r"\g<2>", s)
    # literal: <artifactId>jacoco-maven-plugin</artifactId> ... <version>0.8.5</version>
    s=re.sub(r"(<artifactId>jacoco-maven-plugin</artifactId>\s*<version>)\s*0\.(?:7\.[0-9]+|8\.(?:[0-9]|1[01])(?:\.[0-9]+)?)\s*(</version>)",
             r"\g<1>"+NEW+r"\g<2>", s, flags=re.S)
    if s!=orig:
        open(p,"w").write(s); print("bumped JaCoCo in "+p)
PY

echo "=== java17_compat complete" >&2

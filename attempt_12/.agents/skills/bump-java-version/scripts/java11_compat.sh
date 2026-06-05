#!/bin/bash
# java11_compat.sh <workdir> — deterministic Java-8->11 compat layer applied by the bump
# pipeline (the production agent won't reliably apply failure-table rows, so bake the
# recurring fixes in). Two parts, both idempotent:
#   1. Re-add the Java-EE modules removed in JDK 11 (JAXB, activation, annotation, jaxws)
#      via OpenRewrite AddDependency (onlyIfUsing is too weak for transitive use, so add
#      unconditionally — unused deps are harmless and skipped if already declared).
#   2. Jadira usertype's JavaVersion.<clinit> crashes parsing the single-token "11"; give
#      the surefire-forked JVM java.version=1.8.0 so the parse succeeds (matches what the
#      baseline ran under). Only when org.jadira.usertype is actually present.
set -uo pipefail
WORK=${1:?usage: java11_compat.sh <workdir>}; cd "$WORK"
_jh(){ local v="JAVA_HOME_$1"; printf "%s" "${!v:-${JDK_HOME_BASE:-/opt/jdk}/$1}"; }
MVN="${MVN:-$(command -v mvn >/dev/null 2>&1 && echo mvn || { [ -x ./mvnw ] && echo ./mvnw || echo mvn; })}"

# 1. Re-add the Java-EE modules removed in JDK 11 via a direct pom edit. (OpenRewrite
#    AddDependency only adds when the type is used in *source*, so transitive-only needs
#    like JAXB/activation are silently skipped — a direct edit is unconditional + reliable.)
echo "=== [ee_compat] adding Java-EE-removed deps" >&2
python3 - <<'PY'
import glob, re
deps=[("javax.xml.bind","jaxb-api","2.3.1",""),("org.glassfish.jaxb","jaxb-runtime","2.3.1","runtime"),
      ("com.sun.activation","javax.activation","1.2.0","runtime"),("javax.annotation","javax.annotation-api","1.3.2",""),
      ("javax.xml.ws","jaxws-api","2.3.1","")]
poms=sorted(set(glob.glob("pom.xml")+glob.glob("*/pom.xml")+glob.glob("*/*/pom.xml")), key=len)
root=poms[0] if poms else None     # shallowest = root/parent; a parent's <dependencies> are inherited by every module
if root:
    s=open(root).read(); add=""
    for g,a,v,sc in deps:
        if a not in s:
            add+="<dependency><groupId>%s</groupId><artifactId>%s</artifactId><version>%s</version>%s</dependency>"%(
                 g,a,v,("<scope>%s</scope>"%sc if sc else ""))
    if add:
        # Inject into a REAL top-level <dependencies> (NOT one inside <dependencyManagement>, which
        # only version-manages and never adds the dep — that left jaxb-api inert in reactor parents
        # whose first <dependencies> is the dependencyManagement one). Create a top-level block if none.
        dm=[(m.start(),m.end()) for m in re.finditer(r"<dependencyManagement>.*?</dependencyManagement>", s, flags=re.S)]
        pos=next((m.end() for m in re.finditer(r"<dependencies>", s) if not any(a<=m.start()<b for a,b in dm)), None)
        if pos is not None:
            s=s[:pos]+add+s[pos:]
        else:
            block="<dependencies>"+add+"</dependencies>"
            if "</dependencyManagement>" in s: s=s.replace("</dependencyManagement>","</dependencyManagement>"+block,1)
            elif "</project>" in s: s=s.replace("</project>",block+"</project>",1)
        open(root,"w").write(s); print("added EE deps to "+root)
PY

# 2. Jadira java.version surefire override (only if jadira present)
if grep -rqs 'org.jadira.usertype' --include=pom.xml .; then
  echo "=== [jadira_compat] jadira present -> surefire java.version=1.8.0" >&2
  python3 - <<'PY'
import glob, re
# root pom = the shallowest pom.xml
poms=sorted(glob.glob("pom.xml")+glob.glob("*/pom.xml"), key=len)
root=poms[0] if poms else None
if root:
    s=open(root).read()
    # The fork-effective marker is the surefire systemPropertyVariables block specifically,
    # NOT a bare `java.version>1.8.0` substring: the agent often leaves a stray
    # `<java.version>1.8.0</java.version>` (e.g. a Maven property) that does NOT reach the
    # test fork, so a loose substring guard would false-positive and skip the real override,
    # leaving Jadira's JavaVersion.<clinit> to crash. Guard on the exact block instead.
    block="<systemPropertyVariables><java.version>1.8.0</java.version></systemPropertyVariables>"
    if block not in s:
        # Scope the injection to the maven-surefire-plugin <plugin> element so we never
        # inject systemPropertyVariables into a different plugin's <configuration>.
        m=re.search(r"<plugin>(?:(?!</plugin>).)*?<artifactId>maven-surefire-plugin</artifactId>(?:(?!</plugin>).)*?</plugin>", s, flags=re.S)
        if m:
            blk=m.group(0)
            if "<configuration>" in blk:
                newblk=blk.replace("<configuration>","<configuration>"+block,1)
            else:
                newblk=blk.replace("</plugin>","<configuration>"+block+"</configuration></plugin>",1)
            s=s.replace(blk,newblk,1)
        else:
            plug=("<plugin><groupId>org.apache.maven.plugins</groupId><artifactId>maven-surefire-plugin</artifactId>"
                  "<configuration>"+block+"</configuration></plugin>")
            if "<plugins>" in s: s=s.replace("<plugins>","<plugins>"+plug,1)
            elif "<build>" in s: s=s.replace("<build>","<build><plugins>"+plug+"</plugins>",1)
            else: s=s.replace("</project>","<build><plugins>"+plug+"</plugins></build></project>",1)
        open(root,"w").write(s); print("surefire java.version override added to "+root)
    else: print("override already present")
PY
fi

# 3. Old build plugins (maven-jar/war/assembly) whose bundled plexus-archiver predates
#    JDK 11 and crashes in a <clinit> parsing the single-token "11" java.version
#    (ExceptionInInitializerError / "Index 1 out of bounds for length 1" at JarArchiver.<init>,
#    a *build-time* crash in the main Maven JVM that the surefire override above does NOT reach).
#    Bump the pinned version (property form or literal <version>) to a JDK-11-aware release;
#    only fires when an old 1.x/2.x version is actually pinned, so it's a no-op otherwise.
echo "=== [build_plugin_compat] bumping JDK11-incompatible build plugins (if pinned old)" >&2
python3 - <<'PY'
import glob, re
SAFE = {"maven-jar-plugin": "3.4.1", "maven-war-plugin": "3.4.0", "maven-assembly-plugin": "3.7.1"}
poms = sorted(set(glob.glob("pom.xml")+glob.glob("*/pom.xml")+glob.glob("*/*/pom.xml")), key=len)
for p in poms:
    s = open(p).read(); orig = s
    for art, newv in SAFE.items():
        # property form: <maven-jar-plugin.version>2.6</maven-jar-plugin.version>
        s = re.sub(r"(<"+re.escape(art)+r"\.version>)\s*[12]\.[0-9.]+\s*(</"+re.escape(art)+r"\.version>)",
                   r"\g<1>"+newv+r"\g<2>", s)
        # literal form: <artifactId>maven-jar-plugin</artifactId> ... <version>2.6</version>
        s = re.sub(r"(<artifactId>"+re.escape(art)+r"</artifactId>\s*<version>)\s*[12]\.[0-9.]+\s*(</version>)",
                   r"\g<1>"+newv+r"\g<2>", s, flags=re.S)
    if s != orig:
        open(p, "w").write(s); print("bumped build plugin version(s) in "+p)
PY
echo "=== java11_compat complete" >&2

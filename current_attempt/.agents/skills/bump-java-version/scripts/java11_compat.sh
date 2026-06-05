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
# 4. Old maven-surefire-plugin (2.20.x / 2.21.x and earlier) throws a NullPointerException under
#    JDK 9+ at test-fork startup (a surefire bug fixed in 2.22.0). Three delivery paths:
#      (a) version PINNED in the pom (literal <version> or maven-surefire-plugin.version property) -> bump it.
#      (b) version INHERITED from an old spring-boot-starter-parent (< 2.2 manages surefire < 2.22 via the
#          maven-surefire-plugin.version property) and not otherwise overridden -> ADD that property as a
#          2.22.2 floor; spring-boot-dependencies reads the property, so the child override wins.
#    Only fires when an old surefire is actually in effect, so it is a no-op on modern projects.
echo "=== [surefire_compat] floor JDK9+-incompatible surefire (2.20/2.21 -> 2.22.2; pinned or SB<2.2-inherited)" >&2
python3 - <<'PY'
import glob, re
FLOOR = "2.22.2"
def old_ver(v):                      # True if v < 2.22
    m = re.match(r"(\d+)\.(\d+)", v or "")
    return bool(m) and (int(m.group(1)), int(m.group(2))) < (2, 22)
def old_sb_parent(s):                # spring-boot-starter-parent < 2.2 pins surefire < 2.22
    m = re.search(r"<parent>(?:(?!</parent>).)*?<artifactId>spring-boot-starter-parent</artifactId>(?:(?!</parent>).)*?</parent>", s, flags=re.S)
    if not m: return False
    vm = re.search(r"<version>\s*([0-9][0-9.]*)", m.group(0))
    if not vm: return False
    pm = re.match(r"(\d+)\.(\d+)", vm.group(1))
    return bool(pm) and (int(pm.group(1)), int(pm.group(2))) < (2, 2)
poms = sorted(set(glob.glob("pom.xml")+glob.glob("*/pom.xml")+glob.glob("*/*/pom.xml")), key=len)
for p in poms:
    s = open(p).read(); orig = s
    # (a) literal: <artifactId>maven-surefire-plugin</artifactId> ... <version>2.OLD</version>
    s = re.sub(r"(<artifactId>maven-surefire-plugin</artifactId>\s*<version>)\s*([0-9][0-9.]*)\s*(</version>)",
               lambda m: m.group(1)+FLOOR+m.group(3) if old_ver(m.group(2)) else m.group(0), s, flags=re.S)
    # (a') property: <maven-surefire-plugin.version>2.OLD</...>
    s = re.sub(r"(<maven-surefire-plugin\.version>)\s*([0-9][0-9.]*)\s*(</maven-surefire-plugin\.version>)",
               lambda m: m.group(1)+FLOOR+m.group(3) if old_ver(m.group(2)) else m.group(0), s)
    # (b) inherited from an old spring-boot-starter-parent, no explicit override -> add property floor
    if old_sb_parent(s) and "<maven-surefire-plugin.version>" not in s:
        prop = "<maven-surefire-plugin.version>%s</maven-surefire-plugin.version>" % FLOOR
        if "<properties>" in s:
            s = s.replace("<properties>", "<properties>"+prop, 1)
        elif "</parent>" in s:
            s = s.replace("</parent>", "</parent><properties>"+prop+"</properties>", 1)
        elif "</project>" in s:
            s = s.replace("</project>", "<properties>"+prop+"</properties></project>", 1)
    if s != orig:
        open(p, "w").write(s); print("surefire floor applied to "+p)
PY

# 5. Old Mockito (mockito-core 2.0.x..2.20; its shaded ByteBuddy) defines mock classes via
#    sun.misc.Unsafe.defineClass, REMOVED in JDK 11: every Mockito test then throws
#    "Cannot define class using reflection" / MockitoException, and the cascade of failed
#    Spring-context loads can OOM the test fork. The version is usually pinned by a BOM
#    (spring-boot-dependencies 2.0/2.1, or jhipster-dependencies < 3), so a <mockito.version>
#    property is a no-op and a byte-buddy override is moot (Mockito SHADES byte-buddy) -- must
#    override mockito-core itself. Inject an explicit <dependencyManagement> mockito-core 2.23.4
#    (the JDK11-safe tail of the 2.x line, API-compatible with 2.x projects) + objenesis 3.2 as
#    the FIRST dM entry, so it wins over BOM imports. Narrowly guarded: only on an old
#    mockito-2.x-era stack, and NEVER when the pom already pins mockito-core (respect 3/4/5.x).
echo "=== [mockito_compat] override BOM-pinned old Mockito 2.x -> 2.23.4 for JDK11 (if old-era + unpinned)" >&2
python3 - <<'PY'
import glob, re
OVER = ("<dependency><groupId>org.mockito</groupId><artifactId>mockito-core</artifactId><version>2.23.4</version></dependency>"
        "<dependency><groupId>org.objenesis</groupId><artifactId>objenesis</artifactId><version>3.2</version></dependency>")
def propval(s, name):
    m = re.search(r"<" + re.escape(name) + r">\s*([0-9][0-9.]*)", s)
    return m.group(1) if m else None
def majmin(v):
    pm = re.match(r"(\d+)\.(\d+)", v or "")
    return (int(pm.group(1)), int(pm.group(2))) if pm else None
def old_mockito2_era(s):
    # Spring Boot 2.0.x / 2.1.x BOM pins mockito 2.x in the broken range (2.0 -> 2.15; 2.1 -> 2.23.4 already,
    # so firing there is a harmless no-op). SB >= 2.2 pins >= 2.23 (safe). SB 1.x is Mockito 1.x (a different
    # major -> never bumped here; those are SB1X bails anyway).
    for art in ("spring-boot-starter-parent", "spring-boot-dependencies"):
        m = re.search(r"<artifactId>" + art + r"</artifactId>\s*<version>\s*([0-9][0-9.]*)", s)
        v = m.group(1) if m else None
        if not v:
            pm = re.search(r"<artifactId>" + art + r"</artifactId>\s*<version>\s*\$\{([^}]+)\}", s)
            if pm:
                v = propval(s, pm.group(1))
        t = majmin(v)
        if t and (2, 0) <= t < (2, 2):
            return True
    # jhipster-dependencies BOM: 1.x/2.x -> mockito 2.x era
    jv = propval(s, "jhipster-dependencies.version")
    if jv is None and "jhipster-dependencies" in s:
        jv = "2"   # present but unreadable -> assume old 2.x era
    if jv is not None:
        pm = re.match(r"(\d+)", jv)
        if pm and int(pm.group(1)) < 3:
            return True
    return False
poms = sorted(set(glob.glob("pom.xml") + glob.glob("*/pom.xml") + glob.glob("*/*/pom.xml")), key=len)
for p in poms:
    s = open(p).read(); orig = s
    if re.search(r"<artifactId>mockito-core</artifactId>\s*<version>", s):
        continue   # already pinned (incl. our own prior run -> idempotent); respect the project's choice
    if not old_mockito2_era(s):
        continue
    m = re.search(r"<dependencyManagement>\s*<dependencies>", s)
    if m:
        s = s[:m.end()] + OVER + s[m.end():]
    else:
        block = "<dependencyManagement><dependencies>" + OVER + "</dependencies></dependencyManagement>"
        if "</properties>" in s:
            s = s.replace("</properties>", "</properties>" + block, 1)
        elif "</project>" in s:
            s = s.replace("</project>", block + "</project>", 1)
        else:
            continue
    if s != orig:
        open(p, "w").write(s); print("mockito floor applied to " + p)
PY

echo "=== java11_compat complete" >&2

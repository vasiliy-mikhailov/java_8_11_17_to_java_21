#!/bin/bash
set -uo pipefail
WORK=${1:?usage: sb1_to_sb2.sh <workdir>}; cd "$WORK"
_jh(){ local v="JAVA_HOME_$1"; printf "%s" "${!v:-${JDK_HOME_BASE:-/opt/jdk}/$1}"; }
MVN="${MVN:-$(command -v mvn >/dev/null 2>&1 && echo mvn || { [ -x ./mvnw ] && echo ./mvnw || echo mvn; })}"

JAVA_HOME="$(_jh ${JDK:-8})" ${MVN:-mvn} -B -ntp -Denforcer.skip=true org.openrewrite.maven:rewrite-maven-plugin:6.40.0:run \
  -Drewrite.activeRecipes=org.openrewrite.java.spring.boot2.UpgradeSpringBoot_2_7 \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:6.31.0,org.openrewrite.recipe:rewrite-migrate-java:3.35.0

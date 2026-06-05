#!/bin/bash
set -uo pipefail
WORK=${1:?usage: sb2_to_sb3.sh <workdir>}; cd "$WORK"
JDK=${JDK:-17} mvn -B -ntp -Denforcer.skip=true org.openrewrite.maven:rewrite-maven-plugin:6.40.0:run \
  -Drewrite.activeRecipes=org.openrewrite.java.spring.boot3.UpgradeSpringBoot_3_3 \
  -Drewrite.recipeArtifactCoordinates=org.openrewrite.recipe:rewrite-spring:6.31.0,org.openrewrite.recipe:rewrite-migrate-java:3.35.0

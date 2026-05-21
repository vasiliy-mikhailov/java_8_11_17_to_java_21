# Multi-JDK runner image for the OpenRewrite fitness loop.
# One image, four JDKs (8/11/17/21), Maven 3.9.9, Gradle 8.10.2, git, jq.
# The orchestrator picks the JDK per-repo via the JAVA_HOME indirection in run_one_repo.sh.
#
# JDKs come from official Temurin images via multi-stage COPY rather than
# SDKMAN downloads. Faster and more reliable — SDKMAN's Temurin mirror has
# flaky SSL from some networks (we hit "curl: (28) SSL connection timeout"
# on the 21.0.4-tem fetch even though the base image already ships it).

FROM eclipse-temurin:8-jdk-jammy   AS jdk8
FROM eclipse-temurin:11-jdk-jammy  AS jdk11
FROM eclipse-temurin:17-jdk-jammy  AS jdk17

# Final image already has JDK 21 at /opt/java/openjdk
FROM eclipse-temurin:21-jdk-jammy

ENV DEBIAN_FRONTEND=noninteractive

# OS packages: git, jq, curl, unzip, etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
        bash ca-certificates curl git jq time unzip zip coreutils \
    && rm -rf /var/lib/apt/lists/*

# Alternate JDKs copied from their official images.
COPY --from=jdk8   /opt/java/openjdk /opt/jdk/8
COPY --from=jdk11  /opt/java/openjdk /opt/jdk/11
COPY --from=jdk17  /opt/java/openjdk /opt/jdk/17
RUN ln -s /opt/java/openjdk /opt/jdk/21

# Maven and Gradle.
ARG MAVEN_VERSION=3.9.9
ARG GRADLE_VERSION=8.10.2
RUN curl -fsSL "https://archive.apache.org/dist/maven/maven-3/${MAVEN_VERSION}/binaries/apache-maven-${MAVEN_VERSION}-bin.tar.gz" \
    | tar -xz -C /opt \
    && ln -s /opt/apache-maven-${MAVEN_VERSION} /opt/maven
RUN curl -fsSL "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
        -o /tmp/gradle.zip \
    && unzip -q /tmp/gradle.zip -d /opt \
    && ln -s /opt/gradle-${GRADLE_VERSION} /opt/gradle \
    && rm /tmp/gradle.zip

ENV PATH="/opt/maven/bin:/opt/gradle/bin:/opt/java/openjdk/bin:$PATH" \
    MAVEN_OPTS="-Xmx2g -Dorg.slf4j.simpleLogger.defaultLogLevel=warn" \
    GRADLE_OPTS="-Xmx2g -Dorg.gradle.daemon=false"

WORKDIR /work
COPY scripts /opt/scripts
RUN chmod +x /opt/scripts/*.sh

ENTRYPOINT ["/opt/scripts/run_one_repo.sh"]

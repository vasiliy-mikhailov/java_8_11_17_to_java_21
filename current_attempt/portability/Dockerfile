# Portability-witness container (AGENTS.md P11): a from-scratch host with ONLY
# the JDKs + git + node-for-the-agent. NO system Maven (projects use ./mvnw),
# NO Nexus, NO our wrapper, cold .m2 -> Maven Central direct.
FROM node:20-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends       git curl ca-certificates bash unzip jq     && rm -rf /var/lib/apt/lists/*

# Real Temurin JDKs at /opt/jdk/<major> (jv_from / jv_to selected via JAVA_HOME).
ARG JDKS="8 11 17 21 25"
RUN set -eux; arch=x64;     for v in $JDKS; do       mkdir -p /opt/jdk/$v;       curl -fsSL "https://api.adoptium.net/v3/binary/latest/$v/ga/linux/$arch/jdk/hotspot/normal/eclipse"         | tar xz -C /opt/jdk/$v --strip-components=1;       /opt/jdk/$v/bin/java -version;     done

# The off-the-shelf coding agent under test.
RUN npm install -g opencode-ai 2>/dev/null || curl -fsSL https://opencode.ai/install | bash || true

# Deliberately NO maven on PATH. JAVA_HOME unset (skill/agent sets it per step).
ENV PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
WORKDIR /work

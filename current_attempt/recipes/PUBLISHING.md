# Publishing bump-java-version-recipes to Maven Central

Published as **io.github.vasiliy-mikhailov:bump-java-version-recipes:1.0.0** (namespace verified via GitHub).
The pom has a `release` profile (sources/javadoc/GPG-sign + central-publishing-maven-plugin, autoPublish).

## Republish a new version
1. Bump the `<version>` in pom.xml.
2. settings.xml server id `central` with a Central Portal token:
   `<server><id>central</id><username>TOKEN_USER</username><password>TOKEN_PASS</password></server>`
3. A GPG signing key whose public half is on a keyserver (keys.openpgp.org / keyserver.ubuntu.com).
4. `mvn -Prelease -DskipTests deploy` (autoPublish=true uploads + publishes after validation).

The Java package stays `tech.mikhailov.bump_java_version_recipes` (recipe FQNs unchanged); only the
Maven groupId is `io.github.vasiliy-mikhailov`. The skill's COORDS resolve this from Central, so no
jar bundling is needed once it has propagated.

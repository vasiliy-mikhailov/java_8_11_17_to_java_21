# Publishing bump-java-version-recipes to Maven Central

The pom is publish-ready (metadata + a `release` profile with sources/javadoc/GPG-sign +
`central-publishing-maven-plugin`). The normal build (`mvn package`) is unaffected.
This removes the one portability hack (bundling the recipe jar): once on Central, the skill's
COORDS resolve from any host with no bundling.

## What only the operator can provide (I can't do these autonomously)
1. **Namespace** — register/verify `tech.mikhailov` at https://central.sonatype.com
   (verify ownership of mikhailov.tech via the DNS TXT record the portal shows).
2. **Central Portal token** — generate one in the portal; put it in `~/.m2/settings.xml`:
   ```xml
   <servers><server><id>central</id><username>TOKEN_USER</username><password>TOKEN_PASS</password></server></servers>
   ```
3. **GPG signing key** — `gpg --gen-key`, publish it: `gpg --keyserver keys.openpgp.org --send-keys <KEYID>`.
   Pass the passphrase to the build (`-Dgpg.passphrase=...` or gpg-agent).

## Then publish
```
cd attempt_12/recipes
mvn -Prelease -DskipTests deploy
```
This builds + signs jar/sources/javadoc/pom and uploads to the Central Portal (autoPublish=true).
After it propagates (~15-30 min), the skill needs no bundled jar.

## Note on the groupId
Current groupId is `tech.mikhailov.bump_java_version_recipes` (artifactId `bump-java-version-recipes`).
The Central namespace to verify is `tech.mikhailov`. If you prefer the namespace == groupId,
keep as-is; Central allows sub-namespaces under a verified `tech.mikhailov`.

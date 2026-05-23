# attempt_3 iter-1: null result

Targeted weakest cell j11/jakarta-ee-javax (5/23 = 22% in iter-0).

## Recipe deltas vs iter-0 (= attempt_2 iter-13 champion):

1. **Section 9 (post-pipeline AddDependency)** for jakarta.annotation-api 2.1.x, conditional on jakarta.annotation.{PostConstruct,PreDestroy,Generated,Resource,Nullable,Nonnull} or javax.annotation.{PostConstruct,Generated}. Placed at the end of the composite to survive JakartaEE10s RemoveJakartaAnnotationDependency and UpgradePluginsForJava17s second strip.
2. **jakarta.persistence-api 3.1.x** conditional on jakarta.persistence.{Entity,MappedSuperclass,EntityManager,Id} or javax.persistence.{Entity,MappedSuperclass}.

## Outcome

| | iter-0 | iter-1 | Δ |
|---|---|---|---|
| build_post total | 151/271 (56%) | 150/271 (55%) | **-1** |
| fail → pass flips | n/a | 0 | |
| pass → fail flips | n/a | 1 | |

The regression: `junit4-mockito__j11__11` (active-persistence). After hibernate 5 → 6 upgrade, jakarta.persistence comes in transitively via hibernate-core 6.x. Explicit `AddDependency jakarta.persistence-api 3.1.x` creates a version conflict that breaks `LockModeType` resolution.

The 3 JHipster repos I was targeting in j11/jakarta-ee-javax (`vnpay/com/vn`, `com.one2n.sarathi`, `com.mycompany.test`) all still fail because they need the full Spring Boot 2 → 3 transitive chain restoration: jakarta.servlet, jakarta.persistence, jakarta.validation, jakarta.mail, jakarta.faces. JHipster ships these via `jhipster-dependencies` BOM at version 7.x which doesnt support Jakarta EE 10. Fixing them is bespoke per-repo.

## Verdict

**The iter-13 champion is the plateau on this corpus.** Per fitness #7s repeat clause: stop when only bespoke engineering remains.

What we proved by running iter-1:
- Section 9 mechanic works (post-pipeline AddDependency successfully adds the dep without being stripped — confirmed via pom diff).
- The bigger jakarta-* gaps (servlet, persistence) overlap with the recipes existing transitive-bringing upgrade chain (hibernate-orm 6, spring-boot 3 starters). Adding explicit deps risks conflicts that lose more than they gain.
- The dominant remaining failure modes are bespoke: JHipster BOMs, Lombok JCTree JDK21, individual API removals (`MockMvcRequestBuilders.fileUpload`, `org.hibernate.criterion`, `DbTimestampType`).

## Recommended next step

Either:
- (a) Accept 56% as the champion plateau and write up attempt_3 final summary, or
- (b) Switch fitness focus from build_post % to Qwen quality — i.e., spend iterations on richer Java 21 idiomization (records, pattern matching, sealed types) on the 151 currently-passing repos. The Qwen judge specifically flagged this in iter-0 sample: *"doesnt fully leverage Java 21 features like records or pattern matching"*.

# Union sweep failures — rung-1 per-case verdicts (2026-06-04)

316 green-baselined repos, 258 PASS (81.6%), 58 failures. Each verdict from reading the case individually.

## Verdict distribution

- **FIXED**: 2
- **FIXABLE**: 1
- **SOURCE_MIGRATION**: 3
- **NICHE_BUILD**: 2
- **JHIPSTER_COMPLEX**: 13
- **SB1X_BAIL**: 11
- **ENV**: 2
- **TIMEOUT**: 4
- **STOCHASTIC**: 2
- **NEEDS_RERUN**: 18

## FIXED (2)
- jesperancinha/jeorg-camel-test-drives@0686981f434c (11->17) — surefire --add-opens (java17_compat); committed 7431b557
- mincong-h/java-examples@ec58b6c49e87 (8->11) — EE deps -> real <dependencies> (dependencyManagement bug); committed fa642329

## FIXABLE (1)
- jhipster/jhipster-sample-app-dto@3f4b42939244 (11->17) — old JaCoCo major-61; jacoco bump committed but blocked here by jhipster frontend build17

## SOURCE_MIGRATION (3)
- ozimov/spring-boot-email-tools@729ac0a4c587 (8->11) — nested pom (fixed) + Mockito1.x source API (recipe failed type-attribution)
- prebid/prebid-server-java@73eec79cd492 (11->17) — Spring ReflectionTestUtils.setField signature change
- uhafner/codingstyle@bf538fe487de (11->17) — project assertion API drift (hasNoErrorMessages)

## NICHE_BUILD (2)
- google/google-java-format@13f608bbd6f3 (8->11) — --add-exports jdk.compiler vs --release; needs source/target not release (javac-internals tool)
- google/google-java-format@3c191c1326b7 (11->17) — --add-exports jdk.compiler vs --release; needs source/target not release (javac-internals tool)

## JHIPSTER_COMPLEX (13)
- Cognition-Partner-Workshops/ts-java-angular-jhipster@7ca639077f90 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-cassandra@910667e14cba (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-cassandra@d12f0d084575 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-dto@f595ddfc17c4 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-elasticsearch@95b01cc1ea9b (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-elasticsearch@d53d5779f990 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-gateway@38d86a56cc69 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-microservice@a3fd378fc267 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-mongodb@6b60e4f91d04 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-noi18n@b968d72bdf2e (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-oauth2@3efb97d6ae36 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app-websocket@2cf6d7f94ead (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)
- jhipster/jhipster-sample-app@7ca639077f90 (8->11) — jhipster Angular frontend-coupled build / recipe step fails (or needs Cassandra/Mongo/ES DB)

## SB1X_BAIL (11)
- RyanDozier/webgoat@69d44aed5b2e (8->11) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- SecurityShake/WebGoat@675c506683ec (8->11) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- SharonKoch/WebGoat8_Demo@bad60c43c0f3 (8->11) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- Zvikar72/webgot@007cdaa0d873 (8->11) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- iulspop/WebGoat@b65644edee7f (11->17) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- jaisonyi/webgoat@00deb66ad98a (11->17) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- jegarps/webgoat@0de784eb32d8 (8->11) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- sahilmahale11/webgoat@0e160c19f5b0 (8->11) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- sko1399/WebGoat@80b832676634 (11->17) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- sko1399/WebGoat@cb9503d4a34c (8->11) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)
- turbou/webgoat_pixee@114fbc576062 (8->11) — WebGoat Spring-4.x/SB1.x on JDK11 — manual migration (JAXB/etc. are symptoms)

## ENV (2)
- kennyk65/Microservices-With-Spring-Student-Files@ae3edeaee50a (8->11) — needs external service/DB or network (ConnectException/SQL)
- leonarduk/unison@5c6172067ceb (11->17) — needs external service/DB or network (ConnectException/SQL)

## TIMEOUT (4)
- jerry-tech/Todo-Spring@d5ef12dbb83d (11->17) — heavy build/timeout — not a real failure
- jhipster/jhipster-sample-app-hazelcast@5a867c902acb (8->11) — heavy build/timeout — not a real failure
- jhipster/jhipster-sample-app-hazelcast@a3853f7d037e (8->11) — heavy build/timeout — not a real failure
- rocketbase-io/commons-auth@3f494213a352 (11->17) — heavy build/timeout — not a real failure

## STOCHASTIC (2)
- glytching/dragoman@22287cf80aa3 (11->17) — litellm/harness transient — re-run clears
- mincong-h/java-examples@40993ea9fda5 (11->17) — litellm/harness transient — re-run clears

## NEEDS_RERUN (18)
- Akritai1/Mission_JF@c7a714a590c1 (8->11) — signature=Spring Boot 1.x / Spring 4.x too old
- GastonPerez97/resto-ya@fd664f097bf4 (11->17) — signature=Spring Boot 1.x / Spring 4.x too old
- IlCanMert/seng326-checkstyle@55620a9d2197 (11->17) — signature=other/novel
- JonathanKBP/TesteUnitarioTDD@204a303b4b8b (11->17) — signature=test-exc: ExceptionInInitializerError
- checkstyle/checkstyle@55620a9d2197 (11->17) — signature=other/novel
- folio-org/mod-data-export-spring@fe0914dced9f (11->17) — signature=other/novel
- folio-org/mod-invoice-storage@18bd6827a421 (11->17) — signature=other/novel
- folio-org/mod-invoice@fdde2f45f1c2 (11->17) — signature=other/novel
- gorju/WEBB@99435a107320 (11->17) — signature=Spring Boot 1.x / Spring 4.x too old
- in28minutes/spring-boot-examples@6db697ee4cd4 (8->11) — signature=other/novel
- isa-group/petclinic-react@28a09e273e42 (11->17) — signature=Docker/Selenium env (not a regression)
- kojoampia/jaweb@33db2f4a2af4 (8->11) — signature=other/novel
- kojoampia/jaweb@f6e0de657734 (8->11) — signature=SB2-BOM byte-buddy / ASM (major version 65)
- ppashapu/my-personal-repository@6db697ee4cd4 (8->11) — signature=other/novel
- red6/dmn-check@1f79843e5ea8 (11->17) — signature=compile: COMPILATION ERROR
- skjolber/mockito-rest-spring@9be5a74cd6f2 (8->11) — signature=SB2-BOM byte-buddy / ASM (major version 65)
- ttulka/ddd-example-ecommerce@44781f53ace9 (11->17) — signature=SB2-BOM byte-buddy / ASM (major version 65)
- vaadin/kubernetes-kit@bbb1cba314e6 (11->17) — signature=other/novel

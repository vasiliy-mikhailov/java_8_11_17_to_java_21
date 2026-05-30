This repo sits in the JAXB cluster: a JHipster Java-8 app pinned to
spring-boot 2.0.5.RELEASE and hibernate 5.2.17.Final, with
`hibernate-jpamodelgen` declared at `${hibernate.version}` (5.2.17.Final).

On JDK 11+, `mvn compile` blows up with one of two symptoms before any
OpenRewrite recipe gets a chance to run:

1. `NoClassDefFoundError: javax/xml/bind/JAXBException`
   — JAXB was unbundled from the JDK in 11 and the project still depends
     on `javax.xml.bind.*`. Annotation processors loaded from
     `<annotationProcessorPaths>` need JAXB on the AP classpath, not just
     the compile classpath.

2. `NullPointerException` inside `javac` during annotation processing
   — `hibernate-jpamodelgen 5.2.17.Final` is from the Hibernate-5.2 line
     and NPEs when run inside the JDK 11+ `javac` process. The Hibernate
     5.6 line (`5.6.15.Final`) is the closest stable AP version that
     does not NPE.

Neither problem can be fixed by an OpenRewrite recipe applied to this
project — the project does not compile at the starting state, so no
`mvn rewrite:run` invocation will succeed. The chain must begin with a
`pom_patch` step that edits `pom.xml` directly, BEFORE any rewrite step.

The exact `prep_pom` shape that PASSed on this cluster (8/8 manually):

```json
{
  "label": "prep_pom",
  "jdk": 8,
  "recipes": [
    {"op": "add_dependency", "groupId": "javax.xml.bind",
     "artifactId": "jaxb-api", "version": "2.3.1"},
    {"op": "add_dependency", "groupId": "org.glassfish.jaxb",
     "artifactId": "jaxb-runtime", "version": "2.3.1"},
    {"op": "add_dependency", "groupId": "javax.annotation",
     "artifactId": "javax.annotation-api", "version": "1.3.2"},
    {"op": "add_ap_path", "groupId": "javax.xml.bind",
     "artifactId": "jaxb-api", "version": "2.3.1"},
    {"op": "add_ap_path", "groupId": "org.glassfish.jaxb",
     "artifactId": "jaxb-runtime", "version": "2.3.1"},
    {"op": "add_ap_path", "groupId": "javax.annotation",
     "artifactId": "javax.annotation-api", "version": "1.3.2"},
    {"op": "force_version", "artifactId": "maven-compiler-plugin",
     "version": "3.11.0"},
    {"op": "force_version", "artifactId": "hibernate-jpamodelgen",
     "version": "5.6.15.Final"}
  ]
}
```

Notes for the chain after `prep_pom`:

- The `prep_pom` step itself stays on `jdk: 8` because the pom edits do
  not need a compile, and routing through JDK 8 avoids the harness's
  `--release` flag handling on the post-step build.
- After `prep_pom`, follow the standard staged J8→J11→J17→J21 chain;
  the OpenRewrite recipes will now succeed because the project compiles.
- Lombok bump (`1.18.30`) and `lombok.version` property update should
  still appear as a separate step before `java8_to_java11`; the JHipster
  parent pom often pins old Lombok that breaks on JDK 17+ even after
  JAXB is fixed.
- Do not add or change anything else inside `prep_pom`; this exact 8-op
  recipe is the empirically minimal one for this cluster.

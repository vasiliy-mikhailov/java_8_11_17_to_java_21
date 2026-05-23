# attempt_2 iter-16 — ChangeType org.hibernate.Query: lands correctly, layer 2 org.hibernate.criterion blocks

## Mutation
`ChangeType: org.hibernate.Query → org.hibernate.query.Query` placed after `MigrateToHibernate63` (which didn't include this specific class rename despite the OR docs implying it should).

## Result on 2 targeted repos
| repo | build_post |
|------|:---:|
| `hibernate-5__j11__6` | 0 |
| `hibernate-5__j11__7` | 0 |

## What worked
Diff confirms `-import org.hibernate.Query;` → `+import org.hibernate.query.Query;` in source — primitive landed cleanly.

## Why no flip
Layer 2 surfaces: `package org.hibernate.criterion does not exist`. The same `Criteria` / `Restrictions` removal-in-Hibernate-6 issue documented as bespoke ([rewrite-hibernate #30](https://github.com/openrewrite/rewrite-hibernate/issues/30)). Requires source-level rewrite to JPA Criteria API — no catalog primitive available.

## Cluster status across remaining failures

| cluster | repos | bespoke? |
|---------|-----:|---------|
| WebSecurityConfigurerAdapter | 7 | yes |
| Hibernate Criterion (Query layer 1 fixed, criterion layer 2 remains) | 4 | yes |
| Springfox Docket + Tag + ApiInfo | 4 | yes |
| TemplateResolver (Thymeleaf 3 API change) | 2 | yes |
| ActiveMQ jakarta-jms (Rule layer 1 fixed, ActiveMQ layer 2 remains) | 2 | yes |
| CDI ApplicationScoped layer 3 mixed types | 2 | yes |
| boot.sql.init layer 2 = WebSecurityConfigurerAdapter | 2 | yes |
| EnableEurekaClient (annotation removed, layer 2 = WebSecurityConfigurerAdapter) | 2 | yes |
| jakarta.interceptor cascade (servlet+CDI fixed, JEE cascade) | 1 | yes |
| LocalSessionFactoryBean (Spring orm.hibernate4 gone) | 1 | yes |
| getReferenceById / getHibernateProperties (Spring Data API change) | 2 | yes |
| spotbugs Groovy/Java21 (parent-pom-managed) | 2 | yes |

**Every remaining cluster needs bespoke engineering.** Per #7 Repeat clause: terminate.

## Final champion: iter-13 (56/96, 58% build_post, mean Qwen 3.15/5)
The iter-16 `ChangeType` primitive is kept in the recipe as a quality improvement — it will help any future repo whose ONLY issue is the `org.hibernate.Query` package move.

# attempt_2 iter-14 — junit4-mockito j17 4/6 confirms iter-9 coverage but layer-2 ActiveMQ surfaces

## Targeted result
| repo | iter-7 error | iter-14 error |
|------|------|------|
| `junit4-mockito__j17__4` | `cannot find symbol class Rule` | `incompatible types: org.apache.activemq.ActiveMQConnectionFactory cannot be converted to jakarta.jms.ConnectionFactory` |
| `junit4-mockito__j17__6` | same | same |

Both still build_post=0, but **iter-9's junit-retention primitive resolved the original `class Rule` failure** — layer 2 (ActiveMQ pre-6.x not implementing `jakarta.jms.ConnectionFactory`) now surfaces.

## Per #7: bespoke layer 2
ActiveMQ migration from `org.apache.activemq:activemq-client` (javax-only) to `org.apache.activemq:activemq-client-jakarta` or `6.x` requires a coordinated dep upgrade plus possibly source-level changes — beyond `AddDependency`/`UpgradeDependencyVersion` range without breaking the rest.

## Side discovery
iter-9's `AddDependency: junit:junit:4.13.x` conditional on `org.junit.Rule` fires on these repos too (not just the original targeted batch). The primitive has broader coverage than the targeted test indicated.

## Champion stays iter-13 (56/96, 58%)

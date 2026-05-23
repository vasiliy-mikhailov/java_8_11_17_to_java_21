# attempt_2 iter-15 — RemoveAnnotation @EnableEurekaClient: primitive works, layer 2 WebSecurityConfigurerAdapter

## Mutation
`org.openrewrite.java.RemoveAnnotation: @org.springframework.cloud.netflix.eureka.EnableEurekaClient` — annotation removed in Spring Cloud 2023+; Spring Boot 3 auto-configures Eureka client from the dep alone.

## Result on 2 targeted repos
| repo | build_post |
|------|:---:|
| `spring-boot-2__j8__3` | 0 |
| `spring-boot-2__j8__7` | 0 |

## What worked
The diff shows the primitive **landed correctly** in both repos:
```
-import org.springframework.cloud.netflix.eureka.EnableEurekaClient;
-@EnableEurekaClient
```

## Why no flip
Layer 2: `SecurityCredentialsConfig.java` extends `WebSecurityConfigurerAdapter` (removed in Spring Security 6) with `@Override` methods that no longer exist. Same as the 7-repo `WebSecurityConfigurerAdapter` cluster — community-confirmed bespoke ([#463](https://github.com/openrewrite/rewrite-spring/issues/463)).

Even with this annotation resolved, the SecurityConfig.java compile errors keep build_post=0.

## Champion stays iter-13 (56/96, 58%)

## Pattern note (per #7)
This is the 5th iteration where a single primitive lands correctly but layer 2 keeps the build failing. The WebSecurityConfigurerAdapter cluster (7 repos) is increasingly the blocker for declarative-only progress — without a way to handle it, the diagnostic sub-loop is near saturation.

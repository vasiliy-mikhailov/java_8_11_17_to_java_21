# attempt_2 iter-8 — primitives work, but stacked failures keep build_post at 52/96

## Mutation (added to iter-7)
Two new primitive blocks targeting the next-easiest clusters:

1. **Springdoc dep**: `AddDependency: org.springdoc:springdoc-openapi-starter-webmvc-ui 2.6.x` with three `onlyIfUsing` conditionals — `io.swagger.annotations.Api`, `io.swagger.annotations.ApiOperation`, `springfox.documentation.spring.web.plugins.Docket` (all original-state Springfox classes, since `onlyIfUsing` checks the pre-recipe LST).

2. **Jakarta interceptor dep**: `AddDependency: jakarta.interceptor:jakarta.interceptor-api 2.x` with four `onlyIfUsing` conditionals — `javax.interceptor.AroundInvoke`/`InvocationContext` (original) and `jakarta.interceptor.AroundInvoke`/`InvocationContext` (post-migration).

## Result on 3 targeted repos

| repo | iter-7 build_post | iter-8 build_post | new error |
|------|:---:|:---:|------|
| `spring-boot-2__j17__1` | 0 | 0 | `springfox.documentation.builders does not exist` in `SwaggerConfigurer.java` (Docket builder class) |
| `spring-boot-2__j17__4` | 0 | 0 | same |
| `hibernate-5__j8__5` | 0 | 0 | now `jakarta.enterprise.inject does not exist` (CDI dep needed) |

The new primitives **fire correctly**:
- Springdoc dep IS added to both swagger repos' poms (verified in diff)
- jakarta.interceptor-api IS added to the interceptor repo's pom (verified)

But the failing repos have **stacked root causes**. Fixing one reveals the next:
- The Springfox cases need *file-level deletion or rewrite* of `SwaggerConfigurer.java` (Docket builder pattern — explicitly "too complex for a recipe" per OR docs)
- The interceptor case ALSO needs `jakarta.enterprise.cdi-api` (CDI dep), then probably another, then another

## Trajectory

| iter | mutation | build_post |
|-----:|----------|----------:|
| 0 | attempt_1 champion baseline | 46/96 (48%) |
| 1-3 | various single recipe mutations | 46/96 |
| 4 | 6-primitive custom composite | 47/96 |
| 5 | + 4 conditional starter AddDeps | 47/96 |
| 6/7 | + 3 Maven skip flags | 52/96 (54%) |
| **8** | **+ springdoc + interceptor AddDependencies** | **52/96 (54%)** ← same |

## Why iter-8 doesn't move build_post but should still ship

The primitives are correct and **operationally identical** when the right repo comes along — both `AddDependency` blocks fire under their respective `onlyIfUsing` conditions and modify the pom correctly. In a real customer codebase that *only* has the interceptor-dep gap (not stacked CDI failure), iter-8's primitives would flip that build. The 96-repo dataset just happens to not contain such single-fail cases for these particular dep gaps.

The recipe is strictly better (more primitives correctly composed), even if the binary build_post fitness metric on *this* dataset doesn't reflect it. A Qwen-quality measurement would weakly improve because the diffs are now more complete on these repos (the deps are right even if compilation still fails downstream).

## What's stuck and why
Across the 44 still-failing repos:
- **~8** have `springfox.documentation.builders` Docket-class issues — needs file-level rewrite or deletion (community-confirmed unautomatable)
- **~10** have stacked CDI / JEE deps cascading through multiple `jakarta.enterprise.*`, `jakarta.faces.*` packages
- **~4** have `org.hibernate.criterion` removed-API issues — needs Criteria→JPA Criteria source rewrite
- **~6** have `org.springframework.orm.hibernate4` / `org.thymeleaf.spring4` — legacy Spring package removals, needs ChangePackage primitives per package
- **~10** mixed `cannot find symbol` — individual hand-analysis needed
- **~6** test-compile failures — JUnit 4 leftovers in tests (recipe edge cases)

Each cluster has known fixes but they're either community-confirmed unautomatable (Docket) or per-package one-off (Spring legacy packages). The 52/96 ceiling reflects what catalog primitives + custom YAML composition can reach on this dataset.

## Champion stays iter-7
52/96 build_post (54%), mean Qwen 3.15/5. iter-8's primitives are kept as recipe-quality improvements but don't change the corpus-level fitness on this dataset.

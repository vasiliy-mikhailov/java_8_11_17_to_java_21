# attempt_2 iter-13 — jakarta.validation-api: 2/2 targeted flips, 54/96 → 56/96 (58%)

## Mutation
Added `AddDependency: jakarta.validation:jakarta.validation-api 3.0.x` conditional on **original-state** Hibernate Validator constraint classes (`org.hibernate.validator.constraints.NotBlank`, `NotEmpty`, `Range`) — placed in the pom-ops block at the top of the recipe, BEFORE `JakartaEE10`.

## Why earlier attempts didn't fire
First attempt anchored on `javax.validation.constraints.*` and `jakarta.validation.constraints.*` — neither matched. The failing repos use `org.hibernate.validator.constraints.NotBlank`, which `JakartaEE10` migrates to `jakarta.validation.constraints.NotBlank`. My conditionals checked:
- Original-state class names (matched by `org.hibernate.validator.*` once I added it) ✓
- Pre-recipe `javax.validation.constraints.NotNull` — wrong class
- Post-migration `jakarta.validation.constraints.NotNull` — wouldn't match anyway since `onlyIfUsing` checks original LST

## Targeted result
| repo | iter-9 build_post | iter-13 build_post |
|------|:---:|:---:|
| `hibernate-5__j8__2` | 0 | **1** |
| `hibernate-5__j8__7` | 0 | **1** |

Pom diff confirms `jakarta.validation-api` added in both.

## Trajectory

| iter | mutation | build_post |
|-----:|----------|----------:|
| 0 | baseline | 46/96 |
| 4 | 6-primitive composite | 47/96 |
| 6/7 | + Maven skip flags | 52/96 |
| 9 | + junit retention | 54/96 |
| 8/10/11/12 | (null — stacked / bespoke) | 54/96 |
| **13** | **+ jakarta.validation-api conditional on Hibernate Validator class** | **56/96 (58%)** |

## Pattern learned (per #7)
For `onlyIfUsing` to fire reliably on declarative AddDependency, anchor it on a **pre-migration class** the recipe is *known to remove or rename* (here: `org.hibernate.validator.constraints.NotBlank` → `jakarta.validation.constraints.NotBlank`). Anchoring on the post-migration class only works if the AddDependency runs *after* the migration recipe (as in iter-9's junit-vintage retention).

This generalises a key #7 insight: candidate-primitive judgment requires knowing the *recipe ordering* relative to source state at the moment `onlyIfUsing` is evaluated.

## Sources
- [OpenRewrite AddDependency onlyIfUsing semantics](https://docs.openrewrite.org/recipes/maven/adddependency) — checked against LST at scan time
- [rewrite-migrate-java JakartaEE10 recipe](https://docs.openrewrite.org/recipes/java/migrate/jakarta/jakartaee10) — confirms `org.hibernate.validator.constraints.NotBlank → jakarta.validation.constraints.NotBlank` mapping

# attempt_4 iter-0 — staged migration baseline

## Headline

**183/271 build_post = 68%**, **+12 percentage points** over attempt_3 iter-0 (151/271 = 56%).
**NET +32 flips** (43 up, 11 down) on the same 271-repo corpus.

Recipe ran in three stages per repo (J8 → 11 → 17 → 21, J11 → 17 → 21, J17 → 21), each stage's OpenRewrite pass invoked under the JDK its source compiles against, working tree persisted across stages.

## Per-cell delta vs attempt_3 iter-0

```
                       iter-0  iter-4   Δ
j8  hibernate-5         9/25    7/25   -2
j8  jakarta-ee-javax   11/24   11/24    0
j8  junit4-mockito     11/24   14/24   +3
j8  spring-boot-2      16/24   17/24   +1
j11 hibernate-5        15/25   15/25    0
j11 jakarta-ee-javax    5/23    9/23   +4
j11 junit4-mockito     10/17   10/17    0
j11 spring-boot-2      18/24   19/24   +1
j17 hibernate-5        18/22   21/22   +3
j17 jakarta-ee-javax   16/24   22/24   +6
j17 junit4-mockito     11/15   14/15   +3
j17 spring-boot-2      11/24   24/24  +13
                       ─────  ─────
                      151/271 183/271  +32
```

## Big wins

- **j17 spring-boot-2 cell went 100%** (24/24). This is where attempt_3 had the catch-22 cluster — Lombok JCTree on JDK 21 + WebSecurityConfigurerAdapter not catching variants. Staged migration ran the `WebSecurityConfigurerAdapter` recipe under JDK 17 (clean LST) before crossing to JDK 21, and the Lombok bump landed via Spring Boot 3 BOM during stage 2.
- **j17 jakarta-ee-javax** jumped +6.
- **j11 jakarta-ee-javax** jumped +4 — the previously-22% disaster cell.

## The drag

- **j8 hibernate-5 regressed -2.** Root cause: stage 2 crosses *multiple* epoch boundaries at once (Spring Boot 2.x→3.x **and** Hibernate 5→6 **and** javax→jakarta), creating dep gaps post-stage 2 that the thin stage 3 can't close (`org.hibernate.annotations` missing, `com.sun.istack` missing).
- 11 total regressions across the corpus, all stage-3-compile-failures triggered by the same epoch-collapse pattern.

## Lesson and fitness update

The epoch-collapse drag motivated the AGENTS.md fitness #4 update: *"when staged, each stage's recipes and dependency versions must be compatible with that stage's Java version, and each stage's pom and source edits persist into the next stage's working tree."* The intelligent agent should derive: no stage crosses multiple library epochs in one pass.

## Next iteration

attempt_4 iter-1 will re-stratify:
- **stage1 (JDK 11):** Lombok + light dep upgrades only
- **stage2 (JDK 17):** Spring Boot **2.7.x latest** + Hibernate **5.6.x latest** + JUnit 4 → 5 (epoch-agnostic) + Springfox → SpringDoc (orthogonal). *No* Spring Boot 3, *no* Hibernate 6, *no* JakartaEE10.
- **stage3 (JDK 21):** Spring Boot 3.3 + Hibernate 6 + JakartaEE10 + WebSecurityConfigurerAdapter + UpgradeSpringSecurity_6_0 + UpgradeJavaVersion 21 + UpgradeToJava21 + RemoveUnusedImports.

Realistic target: 200-210/271 (74-77%).

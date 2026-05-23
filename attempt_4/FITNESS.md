# Fitness spec for attempt_4 — staged migration

Carries items 1-8 from AGENTS.md as of attempt_3 wrap (see `attempt_3/FITNESS.md`), and adds item 9 below to govern attempt_4 specifically.

The motivation: attempt_3 plateaued at **151/271 = 56% build_post** on the single-jump recipe (Java 8/11/17 → 21 in one OpenRewrite pass, all under JDK 21). The dominant residual failure cluster — Lombok < 1.18.30 hitting `JCTree.qualid NoSuchFieldError` on JDK 21 — is a catch-22: OpenRewrite's LST parser needs Lombok to load, and Lombok needs an older JDK to load, so the recipe can never upgrade Lombok before parsing fails. Industry practice (Spring/Hibernate migration guides) is to stage version bumps; this attempt embraces that.

---

9. **Fitness (staged migration):** raise the corpus build-success rate above the single-jump declarative plateau by splitting the migration into per-source-Java-version stages, each running its OpenRewrite pass under a JDK the original source compiles against.
   - **Constraints:** declarative configuration deltas only, but split across N stage recipes (one per intermediate JDK target). Each stage's pom and source edits persist into the next stage's working tree. No custom Java AST recipes.
   - **Search:** for each stage, select the OpenRewrite recipes that this JDK + dep-family combination can actually execute (e.g. `UpgradeSpringBoot_2_7` belongs in the JDK-11 stage because Spring Boot 2.7 still supports Java 8/11; `UpgradeSpringBoot_3_3` and `JakartaEE10` belong in the JDK-17 stage because Spring Boot 3 requires Java 17+). Ground each placement decision in the official upstream migration guide (Spring, Hibernate, Lombok release notes, JUnit/Mockito changelogs).
   - **Reward:** real `build_post 0 → 1` flips on the full corpus, net of regressions vs. attempt_3 iter-0 (151/271). A single stage that flips no repos but un-breaks the catch-22 for a downstream stage counts as positive only when the downstream stage realises the flip.
   - **Repeat:** stage-by-stage; if a stage's intermediate `mvn compile` doesn't succeed on most repos under its target JDK, the stage recipe is wrong (too aggressive) and must be tightened before adding the next stage.

This composes with items 4 / 6 / 7 / 8 — staged migration is a structural reframe of item 4's recipe loop, not a replacement. Items 6 (dataset rediscovery), 7 (per-failing-repo refinement), and 8 (runner saturation) continue to apply.

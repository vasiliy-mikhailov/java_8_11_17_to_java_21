# Portability witness (AGENTS.md P11)

Proves the bump-java-version skill runs under a third-party agent on a from-scratch host
with only JDKs + git + network (no `~/bin/mvn` wrapper, no Nexus, no warm .m2, no OpenHands).

- `Dockerfile` — clean image: public node base + Temurin JDKs 8/11/17/21 + opencode, NO system Maven.
  Build: `docker build -t bump-portability .`
- `opencode.json` — points opencode at an OpenAI-compatible model endpoint (set the API key via env).
- `witness_phase1.sh REPO SHA FROM TO` — deterministic: runs the skill's bump scripts directly.
- `witness_opencode.sh REPO SHA FROM TO` — full witness: opencode (the agent) drives the skill.
  Run inside the container with /skill (the skill dir incl. recipe-artifact), /logs, OC_KEY env.

Validated 2026-06-04: hendisantika/user-management 8->11, opencode+Qwen-FP8, green JDK11 post-test.

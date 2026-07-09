# CHANGELOG

<!-- version list -->

## v0.2.0 (2026-07-09)

### Bug Fixes

- Stage SSH-injection files 0644 so the container user can read them
  ([`cda2143`](https://github.com/ondrasek/agent-container/commit/cda2143c1aa4c9b6ca39c0bb7877f151d7acb65d))

- Wait for the published port to release on down before returning
  ([`d58325a`](https://github.com/ondrasek/agent-container/commit/d58325ab106b881d3427b03f6a15be8d373892cd))

- **orchestration**: Bring compose + Quadlet templates to six-volume parity
  ([`4f62c11`](https://github.com/ondrasek/agent-container/commit/4f62c1141809aa3d899f839ae60eee223ad6fffd))

- **security**: Scope git credential helper to https://github.com
  ([`e28cc7e`](https://github.com/ondrasek/agent-container/commit/e28cc7e9597c4ec56595bd92d65b16982a127874))

### Build System

- Require Python 3.14 and add ty + bandit to the quality gate
  ([`df49c6b`](https://github.com/ondrasek/agent-container/commit/df49c6be9f398bd59ea25f76b07f9074e335afc3))

### Chores

- Add spec-kit (.specify) scaffolding
  ([`dde2915`](https://github.com/ondrasek/agent-container/commit/dde2915de53b5761d361468b7be831648fd85910))

- Track .claude/settings.json to share the quality-gate Stop hook
  ([`4b4ce1c`](https://github.com/ondrasek/agent-container/commit/4b4ce1c45de09a12e0ed4007a316608202a4c91f))

### Code Style

- Adopt ruff format + enforce ruff format --check in CI
  ([`c5d1773`](https://github.com/ondrasek/agent-container/commit/c5d1773f1badbbed90d7f8b5861d288268e8040c))

### Continuous Integration

- Add shared quality gate (Stop hook + CI job, one source of truth)
  ([`4bbf096`](https://github.com/ondrasek/agent-container/commit/4bbf09679d819e7b9c99cd0e0c0404efd632c17a))

- Bump actions to Node 24 majors to clear deprecation warning
  ([#1](https://github.com/ondrasek/agent-container/pull/1),
  [`71e9aa4`](https://github.com/ondrasek/agent-container/commit/71e9aa4ddf041c33e51c74cc5aaba778ff2d91a9))

- Enforce Conventional Commits (local hook + CI + ruleset)
  ([`9423053`](https://github.com/ondrasek/agent-container/commit/9423053d37a3c3c8172c3cf27a52fa5e69c479dd))

- Make ty and the acceptance job resolve/run under Python 3.14
  ([`7d3215f`](https://github.com/ondrasek/agent-container/commit/7d3215f2ff6d5d772045d79dd2aa67900f2ce0fc))

- Phase 1 quality gates — ruff lint, Python matrix, CLI --version
  ([`10f1826`](https://github.com/ondrasek/agent-container/commit/10f18260ece2af9dd3d1cf2a14c7d0c74a57041b))

- Phase 2 — release-please scaffolding (automated semver Release PR)
  ([`b610c0f`](https://github.com/ondrasek/agent-container/commit/b610c0fcf91a67ba846768958d1555b0484fdbbd))

- Pin setup-uv to v7 (no floating v8 major tag exists)
  ([#1](https://github.com/ondrasek/agent-container/pull/1),
  [`2550bce`](https://github.com/ondrasek/agent-container/commit/2550bce144a6c85f2830eb96052446f6c6fc5839))

- Point ty at the deps venv explicitly (--python) so it resolves imports
  ([`188168b`](https://github.com/ondrasek/agent-container/commit/188168b4cea3a7232edc026211700e7a676bcd1d))

- Replace release-please with python-semantic-release (Continuous Deployment)
  ([`d67515e`](https://github.com/ondrasek/agent-container/commit/d67515ee021d63619c2aa0e220ea848ad1995239))

### Documentation

- Amend constitution to v1.1.0 (accuracy + compat clause + Principle VI)
  ([`da2f066`](https://github.com/ondrasek/agent-container/commit/da2f066b2c9453ba34bf814d0278379d96f4342d))

- Amend constitution to v2.0.0 (redefine Principle I as Ephemerality)
  ([`2042d84`](https://github.com/ondrasek/agent-container/commit/2042d844749ad015a7fcff576a29ebec2d8c0765))

- Amend constitution to v2.1.0 (add Principle VII — Continuous Deployment)
  ([`e3b8a8d`](https://github.com/ondrasek/agent-container/commit/e3b8a8d88e95820a58613051c42065f79292ab2e))

- Broaden Principle III to Least Exposure (dual of Least Privilege)
  ([`56f252f`](https://github.com/ondrasek/agent-container/commit/56f252f6e3df927d54d373f4d797cc3970153fd1))

- Raise Principle II to invariant altitude (Least Privilege, Immutable Runtime)
  ([`acf2ace`](https://github.com/ondrasek/agent-container/commit/acf2aced3b2a30d2a49b6dd674ff17aa4adc73ad))

- Raise Principle IV to invariant altitude (Deterministic Identity)
  ([`6230e5b`](https://github.com/ondrasek/agent-container/commit/6230e5b8c6d43a46aa5a7113faabf2c51287453f))

- Ratify agent-container constitution v1.0.0
  ([`881b901`](https://github.com/ondrasek/agent-container/commit/881b90102e30f87ba911ab2755484684553272b1))

- Reframe Principle V as Durable Spec, Disposable Code
  ([`8760318`](https://github.com/ondrasek/agent-container/commit/87603182202dc86f5b1c9ed6dffa72524221b1a3))

- Reframe Principle VI to Least Dependencies (completes the Least-X trilogy)
  ([`67ce090`](https://github.com/ondrasek/agent-container/commit/67ce090aa8bee4b320314c68d415d95a0973f767))

- Refresh intro triad + fix stale Principle I cross-reference (Bite 8)
  ([`32adb35`](https://github.com/ondrasek/agent-container/commit/32adb354a95fb8a8823e12a86d0fbea13398721f))

- Remove orphaned rationale left by the Principle VI reframe
  ([`de4af24`](https://github.com/ondrasek/agent-container/commit/de4af249440a1fba84595d7a01d0b5ec76d94ae9))

- Trim Development Workflow section to policy; relocate mechanics to CLAUDE.md
  ([`0cc4614`](https://github.com/ondrasek/agent-container/commit/0cc4614bdf4a2d4b01c27b0ea2a8621ef9344c7d))

### Features

- **cli**: Keys subcommand for live SSH-key injection (no recreate)
  ([`36ea6fe`](https://github.com/ondrasek/agent-container/commit/36ea6fefddcbcc99234a32b587fef5e68129a51c))

- **cli**: Up --host-key / --authorized-key SSH injection flags
  ([`57d900e`](https://github.com/ondrasek/agent-container/commit/57d900e15667880c723c8bb255562cb298cfe2e5))

- **rootless**: Rootless container + persisted, injectable SSH identity
  ([`5676fd8`](https://github.com/ondrasek/agent-container/commit/5676fd83bfd89f84013258c9f110ef542014165c))

### Testing

- Dump container status + logs when acceptance sshd never comes up
  ([`31242dd`](https://github.com/ondrasek/agent-container/commit/31242dd987fcb4761eba856869cfea8222e238f4))

- Migrate suite toward Principle V (inverted pyramid, validation-first)
  ([`dce3e4b`](https://github.com/ondrasek/agent-container/commit/dce3e4b699195fd9e57d8fd5bc23e4446bd436cd))

- **ci**: Run shell suites in CI + cover entrypoint credential/require_env
  ([`2ee0660`](https://github.com/ondrasek/agent-container/commit/2ee066045c4943d9e105cfd98552286d8f3e36c5))

### Breaking Changes

- The agent-container CLI now requires Python >= 3.14 to install and run; Python 3.11-3.13 are no
  longer supported.


## v0.1.0 (2026-07-06)

- Initial Release

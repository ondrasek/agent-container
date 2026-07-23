# CHANGELOG

<!-- version list -->

## v0.13.0 (2026-07-23)

### Chores

- Sync uv.lock to released version 0.11.1
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`0ddaaa3`](https://github.com/ondrasek/agent-container/commit/0ddaaa33b442e3b3f39ff0bad28ab4908acddca8))

### Features

- **cli**: Declarative host provisioning + SSH-key credential routing for agent-as-code
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`9396f8f`](https://github.com/ondrasek/agent-container/commit/9396f8fba0164cad7b4ba9097c49381b6c5e7594))


## v0.12.0 (2026-07-23)

### Features

- **cli**: Field-level drift, convergence, and scoped destroy for agent-as-code
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`ae70bee`](https://github.com/ondrasek/agent-container/commit/ae70beee1bb4b1284e39009fa82456219f2ac941))


## v0.11.1 (2026-07-23)

### Bug Fixes

- **cli**: Raise wait_port_released ceiling to 30s
  ([`3d4d84d`](https://github.com/ondrasek/agent-container/commit/3d4d84dada755efe212a640bb7ab113d7837a3d0))

### Continuous Integration

- Run push CI only on main; never cancel main runs
  ([`8784da1`](https://github.com/ondrasek/agent-container/commit/8784da1a95aee964418066c368b4640194a5eb46))


## v0.11.0 (2026-07-23)

### Bug Fixes

- **aac**: Address US2 adversarial-verification findings
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`aac5373`](https://github.com/ondrasek/agent-container/commit/aac537376e7bc9d18e37f603840ed249195b1664))

### Chores

- **deps**: Sync uv.lock to 0.9.0 ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`5d4e85b`](https://github.com/ondrasek/agent-container/commit/5d4e85b6618b1e505ffd125fcf7d24c8e311b85f))

### Documentation

- **aac**: Clarify the source=file FR-015 detection boundary
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`4faeb73`](https://github.com/ondrasek/agent-container/commit/4faeb73cfb492187aabf5c5a5eaff2602628a827))

- **specs**: Align US2 task text with resolve_credential_value
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`724483a`](https://github.com/ondrasek/agent-container/commit/724483a03eb8927c13de6e477898a3471a1777d0))

### Features

- **aac**: US2 — resolve declared credential references at apply
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`e5f5346`](https://github.com/ondrasek/agent-container/commit/e5f534607b1b761549c8121faa4e90ec214533a0))


## v0.10.0 (2026-07-22)

### Bug Fixes

- **aac**: Address adversarial-verification findings
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`5cc457e`](https://github.com/ondrasek/agent-container/commit/5cc457e4aaf7d3ac300ba0866b468fee5f267f69))

### Chores

- **deps**: Lock PyYAML for agent-as-code
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`38956d1`](https://github.com/ondrasek/agent-container/commit/38956d19e01c5b410055e9ec01bc166543572aae))

### Continuous Integration

- Add pyyaml pin to the pytest jobs for agent-as-code
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`baad2ca`](https://github.com/ondrasek/agent-container/commit/baad2ca838a318fbf82632ead38c1304cc13b775))

### Documentation

- **aac**: Document the declarative agent-as-code model
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`90ad959`](https://github.com/ondrasek/agent-container/commit/90ad9598d11c2348db141f20825f764d33f5751a))

- **specs**: Address analyze findings for Feature 006
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`5eaefa1`](https://github.com/ondrasek/agent-container/commit/5eaefa1e3bd36ce4d4f74f3d8fed3469d3116ddc))

- **specs**: Clarify Feature 006 agent-as-code
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`1db95eb`](https://github.com/ondrasek/agent-container/commit/1db95eb688709c2f2701c990305881847659fc39))

- **specs**: Mark 006 clarification checklist item complete
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`fe41e58`](https://github.com/ondrasek/agent-container/commit/fe41e58fb7a010aca2fafe175ab142d57293add9))

- **specs**: Pin Feature 006 spec format to YAML/PyYAML
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`7c05bb9`](https://github.com/ondrasek/agent-container/commit/7c05bb9b0035ce8ccf0e95d69b30b2c90c97c14b))

- **specs**: Plan Feature 006 agent-as-code + spec-integrity FR-020
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`7a49e9a`](https://github.com/ondrasek/agent-container/commit/7a49e9a45ca86053ec6fbd224128badd0b9573b8))

- **specs**: Task list for Feature 006 agent-as-code
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`3393961`](https://github.com/ondrasek/agent-container/commit/339396166a50b65f166d85d62ea0939eda60df9f))

### Features

- **aac**: Declarative .agent-container project — apply/plan/status/destroy
  ([#006](https://github.com/ondrasek/agent-container/pull/6),
  [`fd09368`](https://github.com/ondrasek/agent-container/commit/fd09368b4c27e67ca458c710528a446a9aa882e5))


## v0.9.0 (2026-07-22)

### Bug Fixes

- **shell**: Strip ssh:// passwords + reconcile --endpoint + docs
  ([#005](https://github.com/ondrasek/agent-container/pull/5),
  [`2ec843d`](https://github.com/ondrasek/agent-container/commit/2ec843da8231c1d966e0497c0ead21fcd2586f8a))

### Chores

- **deps**: Sync uv.lock to released 0.8.0
  ([#005](https://github.com/ondrasek/agent-container/pull/5),
  [`340413c`](https://github.com/ondrasek/agent-container/commit/340413c218cb2ce875f267da9b6dd4e92cfa0678))

### Documentation

- **specs**: Address analyze findings for Feature 005
  ([#005](https://github.com/ondrasek/agent-container/pull/5),
  [`de9fdda`](https://github.com/ondrasek/agent-container/commit/de9fdda03bd36af666de81026714be657b5f06c6))

- **specs**: Clarify Feature 005 shell-integration
  ([#005](https://github.com/ondrasek/agent-container/pull/5),
  [`4f85d8b`](https://github.com/ondrasek/agent-container/commit/4f85d8bdaa836e4fd32279050d967d0a86a67c58))

- **specs**: Plan Feature 005 shell-integration
  ([#005](https://github.com/ondrasek/agent-container/pull/5),
  [`8bae3cd`](https://github.com/ondrasek/agent-container/commit/8bae3cd9de20e403a01bdb1612223d17c659e7e3))

- **specs**: Task list for Feature 005 + add PowerShell dialect
  ([#005](https://github.com/ondrasek/agent-container/pull/5),
  [`32b8014`](https://github.com/ondrasek/agent-container/commit/32b80141ea5e0aad708346994e2073c399b45614))

### Features

- **shell**: Print/emit surface — attach --print + host env
  ([#005](https://github.com/ondrasek/agent-container/pull/5),
  [`3f2d081`](https://github.com/ondrasek/agent-container/commit/3f2d0817077c462e3f101ed4d77c0547cf63c2eb))


## v0.8.0 (2026-07-22)

### Bug Fixes

- **execution**: Clarify clone-on-start HTTPS credential log
  ([#004](https://github.com/ondrasek/agent-container/pull/4),
  [`889ebb7`](https://github.com/ondrasek/agent-container/commit/889ebb77dbba4e891d8727dc0858de4b1af5619a))

### Documentation

- **execution**: Correct the task-delivery guarantee wording
  ([#004](https://github.com/ondrasek/agent-container/pull/4),
  [`8a64683`](https://github.com/ondrasek/agent-container/commit/8a646837e0bf707d32b8518440a2ea60b5f7bc2f))

- **specs**: Apply analyze remediation H1/M1/M2/M3 for Feature 004
  ([#004](https://github.com/ondrasek/agent-container/pull/4),
  [`3789a07`](https://github.com/ondrasek/agent-container/commit/3789a078ecc1cbdf6847819206fd204dabe648f1))

- **specs**: Fold in --foreground guard and headless re-up semantics
  ([#004](https://github.com/ondrasek/agent-container/pull/4),
  [`33ee5cd`](https://github.com/ondrasek/agent-container/commit/33ee5cd06d4a46bf9aaa3533dcf0edf050c49633))

- **specs**: Note headless-foreground sidecar caveat for M1
  ([#004](https://github.com/ondrasek/agent-container/pull/4),
  [`210641d`](https://github.com/ondrasek/agent-container/commit/210641d91f3d5b630bcb2b47cf6f6d46880bb94e))

- **specs**: Plan Feature 004 agent-execution
  ([#004](https://github.com/ondrasek/agent-container/pull/4),
  [`f0ef779`](https://github.com/ondrasek/agent-container/commit/f0ef779fc5ed3e00a2a1da9b23b5e5a0ee25bc59))

- **specs**: Task list for Feature 004 agent-execution
  ([#004](https://github.com/ondrasek/agent-container/pull/4),
  [`b8f586b`](https://github.com/ondrasek/agent-container/commit/b8f586b9b8b6aa41602677948c03bca9759239d8))

### Features

- **execution**: Agent execution modes, sessions & workspaces
  ([#004](https://github.com/ondrasek/agent-container/pull/4),
  [`4ea731a`](https://github.com/ondrasek/agent-container/commit/4ea731a9afb2bb1284fb4769d4832327d63e2990))


## v0.7.0 (2026-07-16)

### Chores

- Sync uv.lock package version to 0.6.0 ([#003](https://github.com/ondrasek/agent-container/pull/3),
  [`599512a`](https://github.com/ondrasek/agent-container/commit/599512aae5fdb2317a638fcb998bb7f8287220ed))

### Continuous Integration

- Add vulture/xenon/refurb to the quality gate + self-healing ty cache
  ([`a07e721`](https://github.com/ondrasek/agent-container/commit/a07e72165623e118eff96114dc155f543133c6c0))

- Pin vulture/xenon/refurb versions to stop local↔CI drift
  ([#003](https://github.com/ondrasek/agent-container/pull/3),
  [`a844ea8`](https://github.com/ondrasek/agent-container/commit/a844ea875345f8d4f496cb4c6809ee68eeec3781))

- Test stdout only in run_check_nonempty so uv's install line isn't a finding
  ([`e0c6c40`](https://github.com/ondrasek/agent-container/commit/e0c6c40fb5b411d1cc708bff77ffd5b031a70f54))

### Documentation

- Credentialing model + 003 polish (specs/003, #003)
  ([`b83391f`](https://github.com/ondrasek/agent-container/commit/b83391fe8bd1bdb833a01c807aac55896b047085))

- **specs**: Address 003 analyze findings — ephemeral API creds + coverage/convention
  ([#003](https://github.com/ondrasek/agent-container/pull/3),
  [`00d2832`](https://github.com/ondrasek/agent-container/commit/00d28323dc591f71a09290351cd0189da0f4a419))

- **specs**: Plan Feature 003 agent-credentialing
  ([#003](https://github.com/ondrasek/agent-container/pull/3),
  [`e4121d2`](https://github.com/ondrasek/agent-container/commit/e4121d2c08f37d7bfa396ca60bcdf666ec1b9a7a))

- **specs**: Task list for Feature 003 agent-credentialing
  ([#003](https://github.com/ondrasek/agent-container/pull/3),
  [`8b53468`](https://github.com/ondrasek/agent-container/commit/8b5346808465e55000da223131ee4b3a6a138cac))

### Features

- Model/API creds, canonical config, rotation (specs/003 US2/US3/US4, #003)
  ([`68c1c0f`](https://github.com/ondrasek/agent-container/commit/68c1c0f726f2387c43df0fb17494525565f5bc04))

- Outbound SSH push credential, ephemeral (specs/003 US1 MVP, #003)
  ([`82325e9`](https://github.com/ondrasek/agent-container/commit/82325e9c0520b2668573c6dbeab163ba28803012))

### Refactoring

- Simplify chained None-identity check per refurb FURB124
  ([#003](https://github.com/ondrasek/agent-container/pull/3),
  [`225cab0`](https://github.com/ondrasek/agent-container/commit/225cab00323876e1c47272e94fa36caf9af40dbe))


## v0.6.0 (2026-07-14)

### Bug Fixes

- Harden the US3 live-reconcile against dead hosts (specs/002 US3, #002)
  ([`440bbe3`](https://github.com/ondrasek/agent-container/commit/440bbe3d2677043c986e31ace78686b2e1dd56cf))

### Chores

- Sync uv.lock package version to 0.5.0 ([#002](https://github.com/ondrasek/agent-container/pull/2),
  [`15b7576`](https://github.com/ondrasek/agent-container/commit/15b7576beee91668f14b5b35e46d88d4a352ce34))

### Continuous Integration

- Probe ty's own resolution when validating the ty cache
  ([`7cb7a6c`](https://github.com/ondrasek/agent-container/commit/7cb7a6c0b9c9dccb8900a2c51d34401a89eb046d))

### Documentation

- Document the lifecycle verbs, live-reconcile, and sidecars (specs/002 polish, #002)
  ([`e4fd456`](https://github.com/ondrasek/agent-container/commit/e4fd45601deb6348a46ee8a7753a21115489469f))

- **specs**: Plan Feature 002 container-lifecycle (net-new scope)
  ([`28ce646`](https://github.com/ondrasek/agent-container/commit/28ce64652bcee4310afc14109fa5cc06a155ff22))

- **specs**: Resolve 002 analyze finding I1 — redeploy is non-idempotent
  ([#002](https://github.com/ondrasek/agent-container/pull/2),
  [`fdf42cf`](https://github.com/ondrasek/agent-container/commit/fdf42cf029beafbe163241f920815198065eee71))

- **specs**: Task list for Feature 002 container-lifecycle
  ([#002](https://github.com/ondrasek/agent-container/pull/2),
  [`9526262`](https://github.com/ondrasek/agent-container/commit/9526262056a969dace7503113260b1a52f5ffb55))

### Features

- Container lifecycle verbs — stop/start/redeploy/wipe + lock (specs/002 US2, #002)
  ([`ca0fe82`](https://github.com/ondrasek/agent-container/commit/ca0fe82ec179890e4b88cdfaf5d3caa0c0dc5a9b))

- Live-reconcile list against each host + fail-closed host_ps_rows (specs/002 US3, #002)
  ([`a822ffe`](https://github.com/ondrasek/agent-container/commit/a822ffe883fd28bbd0b0bf9504294a8f51cda16f))

- Sidecar helper services sharing the deployment lifecycle (specs/002 US4, #002)
  ([`6668425`](https://github.com/ondrasek/agent-container/commit/666842546613c75a2b9ce3bd556067646cdd2d67))


## v0.5.0 (2026-07-13)

### Bug Fixes

- Make the US3 safe-teardown guard fail-closed (adversarial review)
  ([`1764cd1`](https://github.com/ondrasek/agent-container/commit/1764cd191f1483f45045b29f343f7ceb2d2a51f9))

### Continuous Integration

- Self-heal a broken ty cache in the quality gate
  ([`7a4bc30`](https://github.com/ondrasek/agent-container/commit/7a4bc30aa1880726bc61f072ff5208c8d819c3fc))

### Documentation

- Record US3 safe-teardown (tasks, README, CLAUDE)
  ([`3e0124d`](https://github.com/ondrasek/agent-container/commit/3e0124df3dba9494c8a4421480ed18b28819ac2b))

- **specs**: Reconcile 001 artifacts with the shipped US2 implementation
  ([`4018caa`](https://github.com/ondrasek/agent-container/commit/4018caab5f5cfdf1430ba6716d90839a3cd95137))

### Features

- Add host show / rm / rm --destroy with the safe-teardown guard (specs/001 US3)
  ([`e4e8c37`](https://github.com/ondrasek/agent-container/commit/e4e8c37c44c333808c9b4265b18c88d7bb4bbe23))


## v0.4.0 (2026-07-12)

### Bug Fixes

- Apply adversarial-review fixes to the Hetzner provisioner (specs/001 US2)
  ([`d35f5b7`](https://github.com/ondrasek/agent-container/commit/d35f5b7186a9cfc5dc9986752f546345e00ad066))

- Authenticate provisioned-host docker over an ssh socket-forward
  ([`5a463c6`](https://github.com/ondrasek/agent-container/commit/5a463c6a2002d7e205babe6dc1be4e78b77d721c))

- Authorize Hetzner root via the ssh_keys API, not cloud-init (specs/001 US2)
  ([`81491f9`](https://github.com/ondrasek/agent-container/commit/81491f9e2c4922186a39a94d21ca7d471bd8d924))

- Surface why the Hetzner docker-over-ssh readiness probe fails
  ([`c5f81fe`](https://github.com/ondrasek/agent-container/commit/c5f81fed3f9e2133a1e3e9facd647dd1a1759d7c))

### Continuous Integration

- Annotate pytest failures inline via pytest-github-actions plugin
  ([`192da84`](https://github.com/ondrasek/agent-container/commit/192da844a57c70c6d0227cfb9b835be4c9234950))

- Full-fetch the base ref for the conventional-commits check
  ([`ea16a7d`](https://github.com/ondrasek/agent-container/commit/ea16a7d5214e0f587b242198ff7e39a77a84f206))

### Documentation

- Add shell-integration specification (specs/005)
  ([`de6d759`](https://github.com/ondrasek/agent-container/commit/de6d759f18c4470ef32009317ba4493075bd3573))

- **specs**: Add Feature 006 agent-as-code declarative spec
  ([`524f110`](https://github.com/ondrasek/agent-container/commit/524f1102bd14a09679cbd89e3cc71a748021c616))

- **specs**: Update provisioner contract for the socket-forward automation key
  ([`4089bef`](https://github.com/ondrasek/agent-container/commit/4089bef948e69b448437e3b50088fbf7430d941e))

### Features

- Add Hetzner provisioner and host add --provider (specs/001 US2)
  ([`8adfb05`](https://github.com/ondrasek/agent-container/commit/8adfb0517efa382792a9177dfdb25cd98220d290))

- Make Hetzner readiness timeouts env-tunable (specs/001 US2)
  ([`f6fdf65`](https://github.com/ondrasek/agent-container/commit/f6fdf652c03ed6d28ce28d5674e478fff4c0cf38))

### Testing

- Add opt-in tokened Hetzner provisioning acceptance (specs/001 US2, T026)
  ([`21dee6c`](https://github.com/ondrasek/agent-container/commit/21dee6ca9748200da1e16b697f1864fe1e8951b9))

- Guard the billable Hetzner provisioning test out of CI
  ([`96926c9`](https://github.com/ondrasek/agent-container/commit/96926c95f85960d92dc0280c81ff707abea3aaba))

- Make the Hetzner acceptance test env-configurable (specs/001 US2)
  ([`5753e80`](https://github.com/ondrasek/agent-container/commit/5753e80af8b43750d2b2b9a31f450e53da2507df))


## v0.3.0 (2026-07-10)

### Bug Fixes

- Deliver injected SSH host key via compose config, not secret
  ([`49ce1bc`](https://github.com/ondrasek/agent-container/commit/49ce1bc4baf22db63f5ae8410f7939b310028be9))

- Pin compose volume names to preserve the identity contract
  ([`e3af85e`](https://github.com/ondrasek/agent-container/commit/e3af85e5fb49e2430b7ef781117394c5f403caad))

- Stage injected SSH host key 0644 so the container's dev can read it
  ([`fe1b719`](https://github.com/ondrasek/agent-container/commit/fe1b7195da462e54ad8553c33457112305c870fd))

### Chores

- Add host add/ls commands (specs/001 US1, held pre-release)
  ([`f03fe70`](https://github.com/ondrasek/agent-container/commit/f03fe70eb816256870405a6434024247e96ffb40))

- Add multi-host foundational engine (specs/001 phases 1-2)
  ([`678be55`](https://github.com/ondrasek/agent-container/commit/678be5536383204853131bc828e385fb90b0e3d9))

### Continuous Integration

- Grant contents:read to the manual publish job so checkout works
  ([`c97b79d`](https://github.com/ondrasek/agent-container/commit/c97b79df0bb02d942aab9fd7b2b8ee135c80d7c2))

- Rename release.yml back to publish.yml to match the PyPI publisher
  ([`fd236f0`](https://github.com/ondrasek/agent-container/commit/fd236f004599146594065a8aef9d64019ef9f642))

### Documentation

- Add agent execution & session management specification (specs/004)
  ([`2d67a8a`](https://github.com/ondrasek/agent-container/commit/2d67a8a50ca55d94c39127a3fb27fe05a4a52dec))

- Add agent provisioning & credentialing specification (specs/003)
  ([`8d39f30`](https://github.com/ondrasek/agent-container/commit/8d39f303acb6f0246d21c6b01ed1cd759b63b492))

- Add container lifecycle engine specification (specs/002)
  ([`801113f`](https://github.com/ondrasek/agent-container/commit/801113f945882f3777086f2bdab8bf9dff052a4b))

- Add implementation plan for multi-host deployment (specs/001)
  ([`5063f74`](https://github.com/ondrasek/agent-container/commit/5063f74b824cc751c8540106434616730192278e))

- Add multi-host deployment specification (specs/001)
  ([`891f15f`](https://github.com/ondrasek/agent-container/commit/891f15f28247ee1d208aab04eb426038fdb463fe))

- Add task breakdown for multi-host deployment (specs/001)
  ([`09b871d`](https://github.com/ondrasek/agent-container/commit/09b871dc56da61a66683ca52a585d29e1b6cf8b7))

- Document multi-host hosts/--host and the compose run mechanism (specs/001)
  ([`db60061`](https://github.com/ondrasek/agent-container/commit/db6006139765d4e15496bfec1447cbaf847e4567))

- Record CLI grammar rationale for multi-host (specs/001)
  ([`3ab86f4`](https://github.com/ondrasek/agent-container/commit/3ab86f499269e0d097e8292413a1d13d50529f20))

### Features

- Complete host/--host shell completions and per-host state (specs/001 US1)
  ([`032d57a`](https://github.com/ondrasek/agent-container/commit/032d57ab84b6fca9b4afb8f7052f6645d478acfa))

- Compose-based deploy path with --host (specs/001 US1)
  ([`0709756`](https://github.com/ondrasek/agent-container/commit/0709756e7499dd0f7680a12aa0ffe6cdd8489438))


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

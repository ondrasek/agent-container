# CHANGELOG

<!-- version list -->

## v0.21.0 (2026-08-07)

### Bug Fixes

- **egress**: Bind the boundary resolver to loopback and own its pidfile dir
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`b75df0c`](https://github.com/ondrasek/agent-container/commit/b75df0c3b7f2aaf4c58fb5fb1c75e0a073d3022f))

- **egress**: Close an unrestricted egress channel and make declared ports work
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`5ed4bfa`](https://github.com/ondrasek/agent-container/commit/5ed4bfaea6b94eed7e11dfacf89a1135737932c5))

- **egress**: Constrain the proxy's PORT and close two holes in the fail-open fix
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`5125646`](https://github.com/ondrasek/agent-container/commit/512564675001d18f0d05ba1b953eb3e3e8c5cd1b))

- **egress**: Let ssl_bump decide the intercept path, not http_access
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`7fe0583`](https://github.com/ondrasek/agent-container/commit/7fe0583d35ec739b9cf3a610fd1160df23a5404c))

- **egress**: Refuse rather than deploy unrestricted when a declaration is unreadable
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`766086a`](https://github.com/ondrasek/agent-container/commit/766086a154ffc4ab262cd5ff6d848973b30de0c9))

- **egress**: Run the port-owner migration in both directions
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`f1ed831`](https://github.com/ondrasek/agent-container/commit/f1ed831936945161c42bda60e52b09e385416619))

- **egress**: Stop the healthcheck polluting the refusal record, and make boundary membership drift
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`7d8defd`](https://github.com/ondrasek/agent-container/commit/7d8defd0318ffd77995e3226f3eab48389ab2182))

- **egress**: Wait for the boundary to serve before starting the agent
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`f68e830`](https://github.com/ondrasek/agent-container/commit/f68e830b716bac47ce37ec941fd1d2af446688ba))

- **image**: Meet FR-020a by dropping port 53, not redirecting it
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`cb94139`](https://github.com/ondrasek/agent-container/commit/cb94139b7660eb4e3403609f58cda28eca91486a))

### Documentation

- Record that the last two tier failures were a cold image build
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`e25066f`](https://github.com/ondrasek/agent-container/commit/e25066f8f58aac28890b2d0308e86c0a812d3bdb))

- Record the remaining adversarial-review findings as tasks
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`d261806`](https://github.com/ondrasek/agent-container/commit/d261806435b345b5a79bd75809ebbc115573cfb0))

- **specs**: Prove the Phase B mechanism before building on it
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`817e57f`](https://github.com/ondrasek/agent-container/commit/817e57fa656f48605c6117cdd924df9d241f9387))

### Features

- Join the agent to the egress namespace, with no capability
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`47b0e82`](https://github.com/ondrasek/agent-container/commit/47b0e82a13831163e6323c57f47c78e4a686b30e))

- Make the DNS allowlist real rather than advisory
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`2a52a53`](https://github.com/ondrasek/agent-container/commit/2a52a53afaca1525e68fb24d26e69cc3f7242564))

- One typed egress.allow list driving three surfaces
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`7a16ef8`](https://github.com/ondrasek/agent-container/commit/7a16ef88fb6e34111233a150bf5192a5d428397b))

- Put operator sidecars inside the egress boundary
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`3511294`](https://github.com/ondrasek/agent-container/commit/35112945f3179c2adb1fa83dcaffa3a07e283dd7))

- Refuse a sidecar that could dismantle the boundary it sits in
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`8a6811b`](https://github.com/ondrasek/agent-container/commit/8a6811be2454ea0aba1e36145b867353a7681c07))

- Report WHICH enforcement an environment got, not whether
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`fa4a021`](https://github.com/ondrasek/agent-container/commit/fa4a0210d19fd06202b001096426d269f91b8d53))

- **012**: Finish Phase B remaining tasks and reconcile the docs
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`edf8a67`](https://github.com/ondrasek/agent-container/commit/edf8a671abe16f7c7cb2de6a052b5734b2a3f873))

- **012**: Land T145-T151 with measured limits
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`7d7803c`](https://github.com/ondrasek/agent-container/commit/7d7803cb35d80f152a1480f31759a4878c45732c))

- **egress**: State at deploy time that a ported rule pins its addresses
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`7345411`](https://github.com/ondrasek/agent-container/commit/73454114acc63359d891a507b05ee9f5eef110ed))

- **egress**: Tell the operator which mechanism they actually got
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`16cf2e7`](https://github.com/ondrasek/agent-container/commit/16cf2e7e03cf992892eeb5a2e167746ec6b0f8e8))

- **egress**: Warn when default-deny would break `git push` over SSH
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`397d25f`](https://github.com/ondrasek/agent-container/commit/397d25f7d7c82448b017ac1525461567188cb644))

- **image**: Build the Phase B egress boundary
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`f004537`](https://github.com/ondrasek/agent-container/commit/f004537bc2803df31fff0b3943530697bf03b095))

### Testing

- Assert the port is CLOSED, not that the connection was dropped
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`c021f66`](https://github.com/ondrasek/agent-container/commit/c021f66746e041a556fd69478d0a7cec354438dd))

- Pin the three egress renderings and their disagreements
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`ac923d6`](https://github.com/ondrasek/agent-container/commit/ac923d6c7bbcbcc5abd41053f9c4c2cceb83e74f))


## v0.20.0 (2026-08-04)

### Bug Fixes

- Deliver the allowlist by content, and stop stranding the proxy
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`1b392ea`](https://github.com/ondrasek/agent-container/commit/1b392ead962c3b6fd9f6af61aa0e3ebac9c554ba))

- Make `plan`/`status --json` actually emit something
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`c3dbb18`](https://github.com/ondrasek/agent-container/commit/c3dbb1809abbae429e2503d3b144198eab5125aa))

- Name the environment in credential failures, never the declaration
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`3fa500f`](https://github.com/ondrasek/agent-container/commit/3fa500fd5f15f36166b4583fbdf54a9c3dc1e5b0))

- **image**: Use apk's canonical fuzzy-version syntax
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`3abcaaf`](https://github.com/ondrasek/agent-container/commit/3abcaafa6e4c9fe51972d28a087eae0e7f28f6b8))

- **specs**: Packet filtering is a scope decision, not an impossibility
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`1ecfc91`](https://github.com/ondrasek/agent-container/commit/1ecfc9104f905094fb8ab3b8e382c2256b01912a))

- **specs**: Refuse any operator NO_PROXY rather than comparing
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`d5f3362`](https://github.com/ondrasek/agent-container/commit/d5f3362d8ec27bbf9cb975fcfc8a54d9fabe49b7))

- **specs**: Scope SC-002 to what the proxy can actually guarantee
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`c550d42`](https://github.com/ondrasek/agent-container/commit/c550d42beb6706d76b416ef8c354d1e5994d8f5e))

### Documentation

- Add a threat model, and require it be kept current
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`46dbe3c`](https://github.com/ondrasek/agent-container/commit/46dbe3ca429a47b84be91ad7613bb543717539b5))

- Document egress control, and correct a false claim in CLAUDE.md
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`3cce53a`](https://github.com/ondrasek/agent-container/commit/3cce53aad0d7ea549a8a03c9bfb5bde71692f6e2))

- **specs**: Add US4/US5 — enforcement the agent cannot switch off
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`4a02451`](https://github.com/ondrasek/agent-container/commit/4a02451987de677a5856d57d32dbc23dd6e352fb))

- **specs**: Choose the egress proxy by running four of them
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`8f00e70`](https://github.com/ondrasek/agent-container/commit/8f00e70f84ddca969ed4d1653d08d70500607372))

- **specs**: Clarify Feature 012 egress-provider-control
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`eabc412`](https://github.com/ondrasek/agent-container/commit/eabc412ada8604f76d1489080792a8b1fb20a281))

- **specs**: Clarify US4/US5 — one destination list, and DNS as a third enforcement surface
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`e7fce2e`](https://github.com/ondrasek/agent-container/commit/e7fce2e522629777d050150662a23740a81b0dd6))

- **specs**: Close the remaining Feature 012 analysis findings
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`feea858`](https://github.com/ondrasek/agent-container/commit/feea85883fa0b1299808326a41973200f285a7b3))

- **specs**: Close the US4/US5 clarification — sidecars are inside the boundary
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`519b964`](https://github.com/ondrasek/agent-container/commit/519b9645bb96b2f5b25433f919ffe27763ba7aa8))

- **specs**: Correct FR-007's delivery route in Feature 012
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`b1ac59f`](https://github.com/ondrasek/agent-container/commit/b1ac59f466ddd805ae83c862a145192f4a1db678))

- **specs**: One typed egress.allow list, replacing two keys
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`32f2522`](https://github.com/ondrasek/agent-container/commit/32f2522c307d2824a509ac0e01e1f7e247cd3452))

- **specs**: Plan Feature 012 egress-provider-control
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`7e8da72`](https://github.com/ondrasek/agent-container/commit/7e8da72f3412466bee78e0271074045a057b539e))

- **specs**: Plan Phase B — transparent egress enforcement
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`92983ef`](https://github.com/ondrasek/agent-container/commit/92983ef165804f2701e1673279bc6574a520b727))

- **specs**: Record FR-010's real dependency in Feature 012
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`133ef3f`](https://github.com/ondrasek/agent-container/commit/133ef3f69945f32ea05b1882320793d9a78e643c))

- **specs**: Specify Feature 012 egress-provider-control
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`438e800`](https://github.com/ondrasek/agent-container/commit/438e8000e31a22cae5a974cc2183023d5bd42635))

- **specs**: Task Feature 012 egress-provider-control
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`678e87b`](https://github.com/ondrasek/agent-container/commit/678e87b2ab486950daf844ee7e5113ae7263a056))

- **specs**: Task Phase B — transparent egress enforcement
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`14f7747`](https://github.com/ondrasek/agent-container/commit/14f7747995c4ab4f0ed19f124d1213797910c7bd))

- **specs**: The egress declaration governs ALL egress
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`5cbf5e6`](https://github.com/ondrasek/agent-container/commit/5cbf5e64ce25ed9c9de48ce0c0fb2be5ce7ba7d4))

### Features

- Anchor the egress allowlist and stop parsing YAML with regex
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`f026cc6`](https://github.com/ondrasek/agent-container/commit/f026cc67ac4c27a5104cd4389b64e3f03485a548))

- Declare permitted model providers per environment
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`4f20221`](https://github.com/ondrasek/agent-container/commit/4f20221e70435fdb13fce9e575667d5a1911c3e5))

- Disclose an operator override of the egress proxy
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`0221832`](https://github.com/ondrasek/agent-container/commit/0221832e728b14f07840d2ea1137de7ad997c429))

- Disclose the built-in default provider, honestly
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`642110d`](https://github.com/ondrasek/agent-container/commit/642110d7a3eae52d0822674f09c97bfbb3955b07))

- Enforce the egress declaration, and refuse to break git push
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`52f4098`](https://github.com/ondrasek/agent-container/commit/52f40989e8531dc34e74676fe2e6e82f352abb8e))

- Expose the egress facts through --json
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`0f45366`](https://github.com/ondrasek/agent-container/commit/0f453663e434920fc7ef025b79544db221a17991))

- Make an edited egress declaration trigger a redeploy
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`698e8d0`](https://github.com/ondrasek/agent-container/commit/698e8d0e2989dfb3d489aca77adee419ee2d648d))

- Refuse an operator NO_PROXY that would silently disable egress
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`d827bdb`](https://github.com/ondrasek/agent-container/commit/d827bdb9e2836b3200a7f3d45d14469a9b861c46))

- **specs**: Let Feature 012 declare indirect provider endpoints
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`763a166`](https://github.com/ondrasek/agent-container/commit/763a166d22218fd9da54a1bdb3a7cb310b37cbaf))

### Testing

- Gate the threat model, and close the US4/US5 analysis findings
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`1f7988f`](https://github.com/ondrasek/agent-container/commit/1f7988f92c68049615a7d9751fcebbe592ef1c70))

- Verify egress against real containers; identity unchanged
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`87ed5b1`](https://github.com/ondrasek/agent-container/commit/87ed5b1b556d17815c34c740273eb2b1797e0d71))

- **specs**: Give SC-007 a verifying task in Feature 012
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`e13b579`](https://github.com/ondrasek/agent-container/commit/e13b579afeecd42c0b63dcccb186dc768911b582))


## v0.19.0 (2026-08-04)

### Bug Fixes

- **spec**: Identify .agent-container/ YAML by kind, not by glob
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`def97fb`](https://github.com/ondrasek/agent-container/commit/def97fb7eb1e220a8be360d1b7e344d41de32198))


## v0.18.1 (2026-07-29)

### Bug Fixes

- **build**: Name the image/ move when standing in a pre-011 checkout
  ([`97b1e1c`](https://github.com/ondrasek/agent-container/commit/97b1e1ca8a191f65ab1714a5d1c6c25699ca2a87))

### Testing

- **guards**: Prove every structural drift guard can actually fail
  ([`a71aa65`](https://github.com/ondrasek/agent-container/commit/a71aa650a08bdb85af50305eb43f321bdf62cfa1))


## v0.18.0 (2026-07-28)

### Bug Fixes

- **cli**: Widen build_compose_model's env_file annotation
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`bd63e84`](https://github.com/ondrasek/agent-container/commit/bd63e840e7f9e4caf404c996d85f6a4f045d61ed))

### Code Style

- **specs**: Format the python excerpt in 011 research
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`b503d73`](https://github.com/ondrasek/agent-container/commit/b503d73714f8f5dd309e686234b6ae34985d87c6))

### Documentation

- One authoritative layout map, and retire "project directory"
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`b51d07d`](https://github.com/ondrasek/agent-container/commit/b51d07d73cf624dec602e28c654feed1ff6ff6bd))

- **specs**: Clarify Feature 011 filesystem-layout
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`ea65a19`](https://github.com/ondrasek/agent-container/commit/ea65a19ecc3e727980b113c48bc77130eb69ca95))

- **specs**: Drop the bare ./.env from env resolution
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`fb53a9c`](https://github.com/ondrasek/agent-container/commit/fb53a9c3e677b5d7c46adfb3054c9fff79e498a0))

- **specs**: Fix the remaining analyze findings for Feature 011
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`0400c1e`](https://github.com/ondrasek/agent-container/commit/0400c1e37d2e0ab4d667753c50a87db834d071a2))

- **specs**: Keep plaintext credentials out of the project config dir
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`5bc4eaa`](https://github.com/ondrasek/agent-container/commit/5bc4eaac124b21cb2ff3143659829765c0b83b5a))

- **specs**: Name .agent-container for what it holds, not what it marks
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`9da6d6a`](https://github.com/ondrasek/agent-container/commit/9da6d6a99ed3e1145f9dc8aca27657ccb9ed9543))

- **specs**: Plan Feature 011 filesystem-layout
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`016b908`](https://github.com/ondrasek/agent-container/commit/016b908d68e9c321e1804a192ec420e7dcdd2253))

- **specs**: Repeatable -e/--env-file, stacking in order
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`6269754`](https://github.com/ondrasek/agent-container/commit/6269754606674fbcf6e21b6d4d654b3ed5603092))

- **specs**: Settle project root vs project marker vocabulary
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`cb4a336`](https://github.com/ondrasek/agent-container/commit/cb4a336d6665b9b9e9d9b702d3ccf892e790afbd))

- **specs**: State FR-011 as derived from identity, not promised separately
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`faad955`](https://github.com/ondrasek/agent-container/commit/faad95544c62fba875e18d67fbad0d0872bf5eb6))

- **specs**: Task list for Feature 011 filesystem-layout
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`977771d`](https://github.com/ondrasek/agent-container/commit/977771d632f089a8276f24b8b0ce452939620824))

- **specs**: User configuration, not host configuration
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`608c8a5`](https://github.com/ondrasek/agent-container/commit/608c8a528fbc3f0199f9e9432c78f5857bada361))

### Features

- **build**: Move the image sources into image/
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`4871d19`](https://github.com/ondrasek/agent-container/commit/4871d1940b44f324da7d724cb0811b0e33725581))

- **cli**: -e/--env-file is repeatable and stacks in order
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`4273204`](https://github.com/ondrasek/agent-container/commit/4273204bc5afed39227ba388f104e64d592dee75))

- **cli**: Refuse the pre-011 layout instead of ignoring it
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`0dc72a5`](https://github.com/ondrasek/agent-container/commit/0dc72a562db6beb6e537b4e5b503182451f20a44))

- **cli**: Resolve per-environment files from .agent-container/
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`803cf3e`](https://github.com/ondrasek/agent-container/commit/803cf3e0b2db3530b13e9830e25c14812cea83b8))

- **container**: Rename the shell-env directory to ~/.agent-env
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`f6a84b7`](https://github.com/ondrasek/agent-container/commit/f6a84b721b7d586d93f03df8c403f1908c3b475d))

### Testing

- **acceptance**: Cover the new layout against real containers
  ([#011](https://github.com/ondrasek/agent-container/pull/11),
  [`b0ff950`](https://github.com/ondrasek/agent-container/commit/b0ff950c0435e685b87c845feaf03a3868353c3d))

- **cli**: Enforce that every short flag has a long form
  ([`8d5228b`](https://github.com/ondrasek/agent-container/commit/8d5228bed11fb31c2f4a07e279f629a50b1686e1))

### Breaking Changes

- Completes Feature 011. Projects on the pre-011 layout are refused with every file that must move
  named; there is no compatibility mode. Container names, ports and volume names are unchanged, so
  environments already running stay findable and tear down cleanly -- only file locations moved.

- **container**: The persistent shell environment mounts at /home/dev/.agent-env instead of
  /home/dev/.agent-container. Shell snippets referring to the old path by name need updating; the
  file itself is not lost.


## v0.17.1 (2026-07-27)

### Bug Fixes

- **completions**: Zsh --agent completed nothing; test by executing
  ([#010](https://github.com/ondrasek/agent-container/pull/10),
  [`04c0f8b`](https://github.com/ondrasek/agent-container/commit/04c0f8b35ee51dbe0797131fe2269fbb1f56619e))


## v0.17.0 (2026-07-27)

### Documentation

- Prune CLAUDE.md back under its token budget
  ([#010](https://github.com/ondrasek/agent-container/pull/10),
  [`bf28c8f`](https://github.com/ondrasek/agent-container/commit/bf28c8fc0527a070d1f7cfc63433bb237169869c))


## v0.16.0 (2026-07-26)

### Bug Fixes

- **cli**: Stop turning an in-progress teardown into a fatal port error
  ([`ab190e5`](https://github.com/ondrasek/agent-container/commit/ab190e53859d2dfd282eb197c2f5025280137c9c))

- **test**: Update the list --json acceptance to the versioned envelope
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`5c79814`](https://github.com/ondrasek/agent-container/commit/5c79814bb5a54481eae8803a719bb1097a5e07da))

### Chores

- Sync uv.lock to released version
  ([`29781a2`](https://github.com/ondrasek/agent-container/commit/29781a2ef228d32f0ff604e9db43c36904945ad7))

### Documentation

- **specs**: Clarify Feature 009 agent-operable-cli
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`126ab30`](https://github.com/ondrasek/agent-container/commit/126ab3084df5bba8bdcdc299e780de2a28de12e0))

- **specs**: Plan Feature 009 agent-operable-cli
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`a8cf78e`](https://github.com/ondrasek/agent-container/commit/a8cf78ee3ccabdea9e40c99eeca9512e0bb0c8e3))

- **specs**: Remediate analyze findings for Feature 009
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`210419e`](https://github.com/ondrasek/agent-container/commit/210419ed21e8d1bc5eb4104b9e8d5f9bcc930738))

- **specs**: Second clarify pass on Feature 009 agent-operable-cli
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`107fa9f`](https://github.com/ondrasek/agent-container/commit/107fa9f39d21140ba520c525dd4c6b49a5e027ef))

- **specs**: Specify Feature 009 agent-operable-cli
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`0a4fc33`](https://github.com/ondrasek/agent-container/commit/0a4fc330c148e05b2e4c725daf804223f62eff6a))

- **specs**: Task list for Feature 009 agent-operable-cli
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`6baf17b`](https://github.com/ondrasek/agent-container/commit/6baf17ba7d21ab8064fad8ea959303c77e2c4d55))

- **specs**: The skill enforces --json on every invocation
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`596dbb6`](https://github.com/ondrasek/agent-container/commit/596dbb6df3746aa5fb51ef8a5360d23578a523d6))

### Features

- **cli**: Agent-operable CLI — versioned JSON, coded failures, context, skill
  ([#009](https://github.com/ondrasek/agent-container/pull/9),
  [`d610998`](https://github.com/ondrasek/agent-container/commit/d610998afded50f834f2aa3bdb31c3c00cc2e1fc))

### Breaking Changes

- **cli**: `list --json`, `host ls --json` and `host show --json` now wrap their payload in the
  versioned envelope; the record moves under `data` and carries `schema`/`ok`. Read `.data` to get
  the previous shape.


## v0.15.0 (2026-07-25)

### Bug Fixes

- **build**: Stop shipping operator secrets in the docker build context
  ([`7e8e2bf`](https://github.com/ondrasek/agent-container/commit/7e8e2bfb31479ac4ecacece6abda0b36239e2fee))

### Chores

- Sync uv.lock to released version ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`707fcc8`](https://github.com/ondrasek/agent-container/commit/707fcc8932063b94f069871bb1d91a8b31606dec))

### Documentation

- **specs**: Add credentials requirements-quality checklist for Feature 008
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`05daf6d`](https://github.com/ondrasek/agent-container/commit/05daf6dc5d4d0a7ec0c4e8446b6d52c6345465db))

- **specs**: Clarify Feature 008 credential-managers
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`c71dda1`](https://github.com/ondrasek/agent-container/commit/c71dda132580f73e6e9ee51f81cb785ddcebeee2))

- **specs**: Plan Feature 008 credential-managers
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`51cf28b`](https://github.com/ondrasek/agent-container/commit/51cf28b196793a2f879ab7f6b0c248e5391a665a))

- **specs**: Remediate analyze findings for Feature 008 credential-managers
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`c8ba535`](https://github.com/ondrasek/agent-container/commit/c8ba5359a5f527883c7f1c4f0426a818dbb1bd1b))

- **specs**: Resolve all 9 checklist findings for Feature 008
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`2c0e634`](https://github.com/ondrasek/agent-container/commit/2c0e634cfb15494e5095632aad8cc7f625a02dd4))

- **specs**: Specify Feature 008 credential-managers
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`d0cea0a`](https://github.com/ondrasek/agent-container/commit/d0cea0a80e0b8d6f8d0070b39ca645115a491018))

- **specs**: Task list for Feature 008 credential-managers
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`9695530`](https://github.com/ondrasek/agent-container/commit/9695530e3d7237b3bb458d657b4706b760f640fe))

- **specs**: Work through the 008 credentials requirements checklist
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`eb02706`](https://github.com/ondrasek/agent-container/commit/eb0270647c7ee3c0e571173945d6118dd2dc1a38))

### Features

- **cli**: Credential managers as first-class sources
  ([#008](https://github.com/ondrasek/agent-container/pull/8),
  [`b613b5b`](https://github.com/ondrasek/agent-container/commit/b613b5bc410448e0c834871a1a565f6791a99ff2))

### Breaking Changes

- **cli**: The `encrypted` credential source (age/sops decrypting a committed ciphertext) has been
  REMOVED — secrets must not live in the git remote, even as ciphertext. A spec still declaring
  `source: encrypted` is refused by any command that loads it, with a message naming the migration:
  move the secret into a manager (source: onepassword | bitwarden | command), the OS keychain
  (source: keychain), or a file outside the project / untracked (source: file). See
  docs/agent-as-code.md for the migration recipe.


## v0.14.0 (2026-07-24)


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

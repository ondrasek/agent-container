# CHANGELOG

<!-- version list -->

## v0.35.0 (2026-08-23)

### Documentation

- **keys**: Make the post-deploy admit-set query observe, not re-resolve
  ([#020](https://github.com/ondrasek/agent-container/pull/20),
  [`ebb7e06`](https://github.com/ondrasek/agent-container/commit/ebb7e06d25fc97e02d81f46a6372bbeb586482e3))

- **keys**: Plan the public-key collection
  ([#020](https://github.com/ondrasek/agent-container/pull/20),
  [`70071dc`](https://github.com/ondrasek/agent-container/commit/70071dc54d4d3ce4d90a2c29cbf3179fc5e14074))

- **keys**: Specify what `start` does with a drifted collection
  ([#020](https://github.com/ondrasek/agent-container/pull/20),
  [`b502134`](https://github.com/ondrasek/agent-container/commit/b50213472e70c66fba292fa03eed1a280f00c682))

- **keys**: Tool-created grants become revocable by the collection
  ([#020](https://github.com/ondrasek/agent-container/pull/20),
  [`6ca257c`](https://github.com/ondrasek/agent-container/commit/6ca257cc3b3b79add00c23a5c739f3ab08334a46))


## v0.34.1 (2026-08-22)

### Bug Fixes

- **001**: Attach read hosts.conf directly, so hosts.json never superseded it
  ([#001](https://github.com/ondrasek/agent-container/pull/1),
  [`6d5adb7`](https://github.com/ondrasek/agent-container/commit/6d5adb7220d512aebea53e45f851f4177adba0d1))

- **ci**: The release pipeline went red after every successful release
  ([`9fc05d7`](https://github.com/ondrasek/agent-container/commit/9fc05d7fd514e9537052b4512cb98a846056cc2c))

### Documentation

- **020**: Specify the public-key collection, auto-injected
  ([#020](https://github.com/ondrasek/agent-container/pull/20),
  [`0ab138b`](https://github.com/ondrasek/agent-container/commit/0ab138ba0e91a94d9cc103b0b0fd5da12e95ca3e))

- **threat-model**: Add the 020 maintenance row
  ([#020](https://github.com/ondrasek/agent-container/pull/20),
  [`e6ad0f8`](https://github.com/ondrasek/agent-container/commit/e6ad0f8bf1c001d8f7e44f5df3d9180890eec1a8))


## v0.34.0 (2026-08-22)

### Documentation

- **017**: Correct C17's window, document the blind spot, fix image drift
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`f85065c`](https://github.com/ondrasek/agent-container/commit/f85065c06a618dca2c619f5a20d02a0bd955481c))

### Features

- **observability**: Attribute `logs` and `attach`, the last unattributed actions
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`48adf1e`](https://github.com/ondrasek/agent-container/commit/48adf1ed527ddc2e93f25e6447e7e005a92062ae))

### Testing

- Cover the PODMAN driver path, the tool's default runtime
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`9fe4ed3`](https://github.com/ondrasek/agent-container/commit/9fe4ed3f1b328c8c8c21c78481b966c37715b1f6))


## v0.33.0 (2026-08-22)

### Bug Fixes

- **017**: Two product gaps the acceptance re-run exposed
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`a3c97c8`](https://github.com/ondrasek/agent-container/commit/a3c97c84c211cea64f4db83c56de681ceec2376f))

- **compose**: The deploy path built images with NO build args
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`4013300`](https://github.com/ondrasek/agent-container/commit/4013300ee07bf063e69684c6a200ed931ef3c71b))

- **control-plane**: Remove the stale version pin the 0.32.0 release exposed
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`9c31b48`](https://github.com/ondrasek/agent-container/commit/9c31b4823012d7baf6d6a2dd4d28d21b65a0a402))

- **control-plane**: The base image could not run the package it installs
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`1cda58e`](https://github.com/ondrasek/agent-container/commit/1cda58e059e7897c1eadd743cf2a9c2c0e926b6f))

- **control-plane**: The image could not manage the tool's DEFAULT runtime
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`26f1eaf`](https://github.com/ondrasek/agent-container/commit/26f1eaf30d4d06b9be91c9263218a5f04706c6a4))

- **control-plane**: The image had no container runtime client, so it could manage nothing
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`50716bd`](https://github.com/ondrasek/agent-container/commit/50716bda16ca875c21bed06a5909661f65ab4d59))

- **control-plane**: Wire the control plane's own name, and stop redeploy losing the role
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`373a32f`](https://github.com/ondrasek/agent-container/commit/373a32fae734844ba997fb8d34a5a6f95b7aedfa))

- **test**: A shadowed helper silently regressed three Feature 016 tests
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`d260c1b`](https://github.com/ondrasek/agent-container/commit/d260c1b8b769571780b63db2cd06b2b83c65cd9e))

- **test**: Probe container-to-host REACHABILITY, not name resolution
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`8a79dec`](https://github.com/ondrasek/agent-container/commit/8a79decd81d280d479896a2df293f20127d13f81))

- **test**: The collector tests assumed a Docker-Desktop-only hostname
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`282bbe7`](https://github.com/ondrasek/agent-container/commit/282bbe700975397f2345673c26252aec5d9461cd))

### Documentation

- **017**: Record where the passphrase keygen actually landed
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`3d65f54`](https://github.com/ondrasek/agent-container/commit/3d65f540175fbc33c8257f698ec59facc8233229))

- **017**: The control plane, the dual stack, and CLAUDE.md displacement
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`7a7e58b`](https://github.com/ondrasek/agent-container/commit/7a7e58b8a1685375059672ca6b8837673c4fde6e))

- **constitution**: Ratify Principle VIII — Defaults Belong at the Surface (2.3.0)
  ([`9d8e9e8`](https://github.com/ondrasek/agent-container/commit/9d8e9e85a9899e73efb8489cc9a392328a27b364))

- **threat-model**: Reconcile Feature 017 -- a sixth trust boundary
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`81405ac`](https://github.com/ondrasek/agent-container/commit/81405ac579ecc239cd0469c1f10305a16da6cc68))

### Features

- **control-plane**: Declared scope, and an out-of-scope action that fails visibly
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`288edbf`](https://github.com/ondrasek/agent-container/commit/288edbf20dd01a669b50bd4fc16cc3ca5174b371))

- **control-plane**: Inject the host registry as non-secret configuration
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`767a2a4`](https://github.com/ondrasek/agent-container/commit/767a2a4deebd12030d2aa5539d3b6ffbb3cf2746))

- **control-plane**: Narrow rendering and named unreachable hosts
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`d7af470`](https://github.com/ondrasek/agent-container/commit/d7af4708a32465203d85761396ca6b6077e7f7e1))

- **control-plane**: Revoke -- withdraw a standing key fleet-wide
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`eb33644`](https://github.com/ondrasek/agent-container/commit/eb33644d6b02cbfa5cad45d9123718ed94f05a6c))

- **control-plane**: The semver rule and panic self-exclusion
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`7685ef9`](https://github.com/ondrasek/agent-container/commit/7685ef9d9e758c3d950ab888a8bc0e9ef011b1a4))

- **observability**: Attribute READ-ONLY actions, closing FR-009a's gap
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`11d4d5d`](https://github.com/ondrasek/agent-container/commit/11d4d5d529d035ef98ec907e4ff433417ed10931))

- **observability**: Attribution on management actions
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`1d5f365`](https://github.com/ondrasek/agent-container/commit/1d5f365829ad7257a8c14e269160f9c5af23b6c1))

- **observability**: Telemetry collect and retry
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`47c2005`](https://github.com/ondrasek/agent-container/commit/47c2005b7a2fa7604137b04bd01a13ce6f7e96d9))

- **observability**: Telemetry reconcile -- do the two legs agree?
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`ccd9d77`](https://github.com/ondrasek/agent-container/commit/ccd9d7717042770e36f68f681e26fce84059c253))

- **observability**: The OTLP export path -- curl, write-time, fail-open
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`8c451b8`](https://github.com/ondrasek/agent-container/commit/8c451b8d5bc24939f60bd110af501e49ce39a6e8))

### Refactoring

- Defaults belong at the surface, not in implementations
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`3714fce`](https://github.com/ondrasek/agent-container/commit/3714fcef692fbdddd5eb72c17b960049e4700a36))

### Testing

- **017**: Close S20 and record the T080 gates — 80/80
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`dffe424`](https://github.com/ondrasek/agent-container/commit/dffe424ddb10fae2757aa7edeb4ccfb0632ee349))

- **017**: In-container acceptance was measuring the RELEASED CLI, not this tree
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`2f45c74`](https://github.com/ondrasek/agent-container/commit/2f45c74cf00ff52280eff576bda9cf4909a25d4b))

- **017**: The 80-column check was also measuring the released CLI
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`111ef49`](https://github.com/ondrasek/agent-container/commit/111ef49203818d8b0548de9443f9caac130e83f2))

- **017**: The acceptance tier -- absences, a refusing collector, and a SIGKILL
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`084fcb0`](https://github.com/ondrasek/agent-container/commit/084fcb0b65f34abb47a41ddfdf9253b05d7056a0))

- **017**: The full tier's 8 failures were one leak and three wrong assumptions
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`b6fab86`](https://github.com/ondrasek/agent-container/commit/b6fab8641853c65e9d4732ec1ca21014617fb16d))

- **017**: The last acceptance scenarios -- US1 end to end, revoke, and locking
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`76a9aef`](https://github.com/ondrasek/agent-container/commit/76a9aef873ff488f85975ef99efc44cdb807401d))

- **017**: The reconciliation acceptance scenario S19 was missing
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`ad040af`](https://github.com/ondrasek/agent-container/commit/ad040afd22a88e864cfed8168683922654ed17c0))

- **017**: Three acceptance failures, three different wrong assumptions
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`d1062ab`](https://github.com/ondrasek/agent-container/commit/d1062abbebfd5c5d569f0caa8058a938623783c9))


## v0.32.0 (2026-08-21)

### Chores

- **specs**: Point the speckit cursor at 017
  ([`0df5212`](https://github.com/ondrasek/agent-container/commit/0df521250a8140f1d2cf77d4f8bb42b7803b8205))

### Documentation

- Trim CLAUDE.md under its 2000-token budget, measured properly
  ([`58cbac4`](https://github.com/ondrasek/agent-container/commit/58cbac4e0b4da22288407d3dcbc78be7a3eb3bd0))

- **017**: Split the export-dependency clause from endpoint resolution, and cite R8
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`5c29576`](https://github.com/ondrasek/agent-container/commit/5c2957687ed9b6f0aa40aae0b093a85a85626a80))

- **017**: Stop naming the whole trail after one of its three classes
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`a948728`](https://github.com/ondrasek/agent-container/commit/a948728913fc6e2b8935d83650b4b37e19d5e2de))

- **specs**: A per-record export state that claims only what the client can see
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`b33236e`](https://github.com/ondrasek/agent-container/commit/b33236ed6f1ee8cb556c4002df3e8630a721b8af))

- **specs**: Attribute every control-plane action, drained off the hosts
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`1647fc8`](https://github.com/ondrasek/agent-container/commit/1647fc8c4419597619a9d01407ad92068e390c02))

- **specs**: Both observability legs carry the same payload, defined once
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`b66c544`](https://github.com/ondrasek/agent-container/commit/b66c5441a8d78550e6e3fa53bf870e60773b7f92))

- **specs**: Close 013 — the acceptance tier is green with no selector
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`abfcb70`](https://github.com/ondrasek/agent-container/commit/abfcb70bc1359ad1b061535895b6054c0a578e06))

- **specs**: Collected records land in the operator's durable store
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`f0370e6`](https://github.com/ondrasek/agent-container/commit/f0370e6e235c22372ad7251164bef8df239d96d9))

- **specs**: Confirm 013 ships as feat/MINOR
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`b650239`](https://github.com/ondrasek/agent-container/commit/b650239763227ccd40ad69d9864eb5c7016d5c19))

- **specs**: Define SC-020's window and scope SC-022 to completed exports
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`2481688`](https://github.com/ondrasek/agent-container/commit/24816885dbc2450be72cf804e70cea37732bdecc))

- **specs**: Export fires at write time, per record
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`86ab717`](https://github.com/ondrasek/agent-container/commit/86ab7171df950a150894799578aa91e78746b6fd))

- **specs**: FR-016 becomes a semver rule with a direction
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`5a3bac1`](https://github.com/ondrasek/agent-container/commit/5a3bac10f8a99d005e3694fe5dfadaefa8cb8d72))

- **specs**: Generate tasks for 017 — 65 tasks, census before second image
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`6a56667`](https://github.com/ondrasek/agent-container/commit/6a566675964ae3577a91ae5d39f5b491833b5b57))

- **specs**: Make trail retrieval unconditional, not the no-endpoint path
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`89cfad4`](https://github.com/ondrasek/agent-container/commit/89cfad48127b72d22f54a7491ba780f475daf9fb))

- **specs**: Name the file, not a range, wherever scope was hardcoded
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`01dc269`](https://github.com/ondrasek/agent-container/commit/01dc269a4e6946ee692a87a3f939088ac22d80d4))

- **specs**: Nesting is supported deliberately, and inherits no reach
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`f6714e3`](https://github.com/ondrasek/agent-container/commit/f6714e3ff47cdfea1de16d35a379ba3b8e274155))

- **specs**: OTLP as the export protocol, plus a command to collect logs
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`e878daf`](https://github.com/ondrasek/agent-container/commit/e878daf5cc452a93383463a0fb7f3534b72b5d27))

- **specs**: Plan 017 — three of its pieces do not exist yet
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`a171f93`](https://github.com/ondrasek/agent-container/commit/a171f93d6bcbc40006e74cd5934097469c2a2f47))

- **specs**: Re-plan 017 against the current spec, carrying R2 and R3 verbatim
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`c9f26f5`](https://github.com/ondrasek/agent-container/commit/c9f26f5a1b680c84275538c7e00d552813dca63b))

- **specs**: Re-sync task citations after the re-plan
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`52fb1c7`](https://github.com/ondrasek/agent-container/commit/52fb1c73ac469747cae3c40fea77ef5a16239d39))

- **specs**: Regenerate the observability phase for the dual stack
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`71aaa11`](https://github.com/ondrasek/agent-container/commit/71aaa116bdda8714b3fb289d2e3d34cd4c51de50))

- **specs**: Split correlation out of the task-text clause
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`3dfc25b`](https://github.com/ondrasek/agent-container/commit/3dfc25bcd41e9b7dcc03cad357ad31473d072e51))

- **specs**: State that a task is not a credential channel, and export it
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`0b06a9c`](https://github.com/ondrasek/agent-container/commit/0b06a9c96dea01aef78362487b0baec578bcfdf3))

- **specs**: The attribution trail needs a destination the control plane can't rewrite
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`b2214f0`](https://github.com/ondrasek/agent-container/commit/b2214f029fde52f441ac4c395ac96dce68bce812))

- **specs**: The control plane queries hosts live; it does not sync an inventory
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`737ce65`](https://github.com/ondrasek/agent-container/commit/737ce65961803238b9e55abfedba2dd6525b1049))

- **specs**: The OTLP endpoint is declared at either config level
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`991c773`](https://github.com/ondrasek/agent-container/commit/991c773219f4203adceb2be1ebd499c2f0b3e667))

- **specs**: Widen telemetry export to all containers, never the task text
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`df2b1a9`](https://github.com/ondrasek/agent-container/commit/df2b1a927cbe37c91eaef713d7d241118b876a17))

### Features

- **control-plane**: --role control-plane, the one-shot passphrase, and provenance
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`fab2416`](https://github.com/ondrasek/agent-container/commit/fab24169abb166d2e4d0b276a6f35e2402ac47df))

- **control-plane**: The second image, and a census that can actually see it
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`5dc2cfc`](https://github.com/ondrasek/agent-container/commit/5dc2cfcf7b1a24695a948df2ed1507bda2b08e12))

### Testing

- **doctor**: Assert non-invocation instead of watching for a dialog
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`3d95269`](https://github.com/ondrasek/agent-container/commit/3d952691d162199ab84317c90de591b4c590fb98))


## v0.31.0 (2026-08-17)

### Documentation

- **specs**: Close every analyze finding for 013
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`2889c61`](https://github.com/ondrasek/agent-container/commit/2889c612577b074360f03d769b1a01a8ece2a405))

- **specs**: Generate tasks for 013 — 61 tasks, gate before checks
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`d51cb5b`](https://github.com/ondrasek/agent-container/commit/d51cb5bfd57b44faf3f52a0d794a76d55a482856))

- **specs**: Narrow FR-011's exit range and define the unknown case
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`37a9765`](https://github.com/ondrasek/agent-container/commit/37a9765e1a48bfc0e0c7ac7d78986425a868668b))

### Features

- **doctor**: Machine-level checks, scope reporting, and the docs
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`21a2e3f`](https://github.com/ondrasek/agent-container/commit/21a2e3ff95278f6822301447aeb55b0c3a9f11b7))

- **doctor**: Read-only preflight validation
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`8e96045`](https://github.com/ondrasek/agent-container/commit/8e96045e177c585fa4d7843cd30d33015ec8237e))


## v0.30.0 (2026-08-17)


## v0.29.0 (2026-08-17)

### Features

- **redeploy**: Inherit the clone URL unless told otherwise
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`3215bd4`](https://github.com/ondrasek/agent-container/commit/3215bd43d18c2a791d93678cab10bdb5ca1e8d0c))

### Breaking Changes

- **redeploy**: `redeploy` no longer drops the clone-on-start URL when `--repo` is omitted. A script
  relying on the old reset must now pass `--no-repo`. Note the asymmetry this leaves, and it is
  deliberate rather than overlooked: `--mode`, `--agent` and `--workspace` still fall back to their
  defaults when omitted. Only the clone URL is carried over, because only it was asked for —
  widening the rule to the rest is a separate decision with its own surprises.


## v0.28.1 (2026-08-16)


## v0.28.0 (2026-08-16)

### Bug Fixes

- **ssh-key**: Carry the agent's public key on the list --json row
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`0a06fa8`](https://github.com/ondrasek/agent-container/commit/0a06fa802d0c8c5bc0e7f73daab5e2e157200b3d))

- **ssh-key**: Make the clone DECIDE before the deploy reports on it
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`43a4040`](https://github.com/ondrasek/agent-container/commit/43a40400d7ae98439ce82b6a06e2236b1ae87019))

- **ssh-key**: The pending-clone recovery names a command that works
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`defdcf6`](https://github.com/ondrasek/agent-container/commit/defdcf6296098b0b15b58d02f56cc92895d1131c))

### Documentation

- **specs**: A deferred clone exits non-zero, and must say what NOT to do
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`82b5e07`](https://github.com/ondrasek/agent-container/commit/82b5e0730ae4253c0d93d728d58020fe0f0eae8f))

- **specs**: Close every analyze finding for 019, and document the exit codes
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`286e305`](https://github.com/ondrasek/agent-container/commit/286e30566415a1a205b5f3e7a443954da27b5d64))

- **specs**: Re-plan 019 after four clarifications
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`04864bc`](https://github.com/ondrasek/agent-container/commit/04864bc00bdb30781553843fae169c342db4f60c))

- **specs**: Regenerate tasks for 019 after the re-plan
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`2953409`](https://github.com/ondrasek/agent-container/commit/2953409c592da96ab53049a7bc31784b71027569))

- **specs**: The probe targets the --repo host, or nothing at all
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`3f5711f`](https://github.com/ondrasek/agent-container/commit/3f5711f9cb01f0d1bf7eefb0d7f7827b44c97ad9))

- **specs**: Write ~/.ssh/config once; make rotation an explicit command
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`1d8454f`](https://github.com/ondrasek/agent-container/commit/1d8454f1ae1ae6984ef0fd9b31c8d79c6a294d93))

- **ssh-key**: Reconcile the docs with a feature that is mostly a deletion
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`d0f05d7`](https://github.com/ondrasek/agent-container/commit/d0f05d7d404a50257de3db820602cd513b30f803))

### Features

- **ssh**: The agent generates its own SSH key pair
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`c2610a2`](https://github.com/ondrasek/agent-container/commit/c2610a2bdc300457d154e3ea708d663ee77a9bc3))

### Testing

- **ssh-key**: The hermetic and acceptance tiers for the agent key pair
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`394c0a4`](https://github.com/ondrasek/agent-container/commit/394c0a4c77750effed304b80b3ad4c91955dfa70))

### Breaking Changes

- **ssh**: `up --push-key`, `redeploy --push-key`, the SSH_PUSH_KEY_B64 env-file variable and
  `target: push_key` in a project spec are all removed. Each now fails with a message saying the
  agent generates its own key and the operator registers the PUBLIC half. `--known-hosts` and
  PUSH_KNOWN_HOSTS STAY — they verify the forge, which is the opposite direction and public data.


## v0.27.0 (2026-08-16)

### Documentation

- **specs**: Generate tasks for Feature 019 — PREMISE UNDER REVIEW
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`7fe1210`](https://github.com/ondrasek/agent-container/commit/7fe12101ffacd10422d668f7cab44efa25c3e780))

- **specs**: It is the AGENT SSH KEY PAIR, not a "push key"
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`a51b591`](https://github.com/ondrasek/agent-container/commit/a51b591350540f9d8bec73103ca7dc3a725df16b))

- **specs**: Plan Feature 019 container-generated push key
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`e7a39ed`](https://github.com/ondrasek/agent-container/commit/e7a39edff43b25095f684c0255c41d0c3c8deb48))


## v0.26.0 (2026-08-16)

### Bug Fixes

- **tests**: A host-key refusal must be refused for the RIGHT reason
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`6198c0a`](https://github.com/ondrasek/agent-container/commit/6198c0acc409866b7fe09a7d0cdfe32ac4fc255b))

### Documentation

- **specs**: Close out 015 — full acceptance tier and quickstart verified
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`555cadc`](https://github.com/ondrasek/agent-container/commit/555cadcefb97df943c9bf0f5d7f59a86f4b97b8e))

- **specs**: Generate tasks for Feature 015 kill switch
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`f815d68`](https://github.com/ondrasek/agent-container/commit/f815d68b00afe78987f48a441f66dfe57f468590))

- **specs**: Name the per-host timeout — 30s, and say why not less
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`cd12a1d`](https://github.com/ondrasek/agent-container/commit/cd12a1d900747ddff7f763e2ee720a169bb19f48))

- **specs**: Plan Feature 015 kill switch
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`3c51a44`](https://github.com/ondrasek/agent-container/commit/3c51a441180f8c44fcc3dbda147331303cae02c4))

- **specs**: Repeating the action never turns "we cannot tell" into success
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`e7867a5`](https://github.com/ondrasek/agent-container/commit/e7867a5dd2790e6ed9b24bfa6e5c381e48e6bcd5))

- **specs**: Resolve every analyze finding for Feature 015
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`b3e345c`](https://github.com/ondrasek/agent-container/commit/b3e345c9cb1063ad8b37b41a9340743e1930df8d))

- **specs**: Scope filters on stored inventory fields only
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`5d38cb8`](https://github.com/ondrasek/agent-container/commit/5d38cb843ddda065ac77f37a586872e35b9e768b))

- **specs**: The destroying form has PURGE reach, not wipe
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`78f777a`](https://github.com/ondrasek/agent-container/commit/78f777a2db7bc52d939b0d13c3d2d0be9b8a1f88))

- **specs**: Unreadable refuses, absent succeeds — ratified, not assumed
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`b722f84`](https://github.com/ondrasek/agent-container/commit/b722f84f64b405b683d0de44974a530d57476183))

### Features

- **panic**: A kill switch that tells the truth about what it could not reach
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`58fd42a`](https://github.com/ondrasek/agent-container/commit/58fd42a155b7246d865951c2b1c1f09ea8cfd8e9))

- **panic**: The honest edges — interruption, parallelism, and the threat model
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`7e12b53`](https://github.com/ondrasek/agent-container/commit/7e12b534f73a9227d19bddd6108bb56f5ab20551))


## v0.25.0 (2026-08-15)

### Documentation

- **specs**: Specify Feature 019 — the push key is generated in the container
  ([#019](https://github.com/ondrasek/agent-container/pull/19),
  [`a3ec51e`](https://github.com/ondrasek/agent-container/commit/a3ec51ecf72bf7e4bdab98dd7491165935b4dee0))

### Features

- **inventory**: Reconcile the record against reality, fail-closed
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`7971ea3`](https://github.com/ondrasek/agent-container/commit/7971ea301b124d3060ea9ff91f72099e58bab524))

- **inventory**: Remember every environment the tool created
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`895b619`](https://github.com/ondrasek/agent-container/commit/895b619c02aa5b2298f493bb286e94e18a7b9e55))


## v0.24.0 (2026-08-15)

### Bug Fixes

- **tests**: Repair two checks that only failed on Linux
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`fd37a92`](https://github.com/ondrasek/agent-container/commit/fd37a92fdb9ba8fc0e6667f2ed167f59f1f2c9de))

### Documentation

- **specs**: Add SC-009 so US3 is measurable, and cite FR-002
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`1c9b399`](https://github.com/ondrasek/agent-container/commit/1c9b399647046fb2015d237e8b3f1f0aa0a38a5b))

- **specs**: An absent pin ASKS, a mismatch never does
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`0504cf2`](https://github.com/ondrasek/agent-container/commit/0504cf2761d1ff8b9dd5d11e90be18b039e5ce0a))

- **specs**: Close out 018's task list ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`236c786`](https://github.com/ondrasek/agent-container/commit/236c786026803d46f4fc37e496afdaa9fd43689c))

- **specs**: FR-002 names the inventory a TENANT, not a new location
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`e119abe`](https://github.com/ondrasek/agent-container/commit/e119abeb7f2c945dbf241080618260a36edd4fbe))

- **specs**: FR-014 covers THREE memories, not two
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`cb164ca`](https://github.com/ondrasek/agent-container/commit/cb164ca01db0afcb07b4cd405efc477c41c60493))

- **specs**: Generate tasks for Feature 014 host inventory
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`449bd58`](https://github.com/ondrasek/agent-container/commit/449bd5872337e649c919d5d5e74bd265a5093ec4))

- **specs**: Generate tasks for Feature 018
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`ee9bf1c`](https://github.com/ondrasek/agent-container/commit/ee9bf1c7d725a798f6edb898ef063f28b7a0f1f1))

- **specs**: Name 014's backstop cap — 5000 entries, count only
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`d78c091`](https://github.com/ondrasek/agent-container/commit/d78c091731e465bc48b4db49a8bf8613d7f5d5cf))

- **specs**: Plan Feature 014 host inventory, and qualify 016's SC-008 (#014)
  ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`83830d6`](https://github.com/ondrasek/agent-container/commit/83830d633e0975cea6a7f25903ef51d410764f80))

- **specs**: Plan Feature 018 verified attach
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`ab2510d`](https://github.com/ondrasek/agent-container/commit/ab2510d2971a654cbe37231cfeca3480d22582d8))

- **specs**: Resolve the remaining analyze findings for 018
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`3e34bfc`](https://github.com/ondrasek/agent-container/commit/3e34bfccdd4fc1df1541ce71001cdd239b59d0bd))

- **specs**: Specify Feature 018 — verified attach, no private host key on disk
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`097e37c`](https://github.com/ondrasek/agent-container/commit/097e37c0c38b14a71a09f39931861e28522ea4da))

- **specs**: The inventory begins at install and is not backfilled
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`89c5eec`](https://github.com/ondrasek/agent-container/commit/89c5eec11eb7d0f558cc94a1a5c55b0b717567db))

### Features

- **attach**: Capture at every deploy, and ASK when nothing is pinned
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`aea0a45`](https://github.com/ondrasek/agent-container/commit/aea0a459c8cea3b7942f96ea6fec46cd4db270d2))

- **attach**: Pin the container's host PUBLIC key and verify against it
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`5bcfaeb`](https://github.com/ondrasek/agent-container/commit/5bcfaebb506b9487468938bd160d42443906d3ad))

- **credentials**: Remove every private-host-key channel
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`07e14a3`](https://github.com/ondrasek/agent-container/commit/07e14a30c66bafd20f3e54e806271db71baa533e))

### Testing

- **attach**: Prove the pin actually refuses, against real containers
  ([#018](https://github.com/ondrasek/agent-container/pull/18),
  [`ca7fc5d`](https://github.com/ondrasek/agent-container/commit/ca7fc5d628cc0ea35c169a1eb8fa12dd320b5223))

### Breaking Changes

- **credentials**: `up --host-key`, `keys --host-key`, `redeploy --host-key`, the
  `SSH_HOST_ED25519_KEY_B64` env-file variable, and `target: host_key` in a project's
  `.agent-container/` spec are all removed. Each now fails with a message saying host identity is
  CAPTURED, not supplied -- a bare "no such option" would be a regression rather than a removal,
  because the operator who used the flag had a reason and it is now served without the cost.


## v0.23.0 (2026-08-10)


## v0.22.0 (2026-08-10)

### Bug Fixes

- **observability**: Open the run record before anything slow, and stop the test demanding one
  before the run starts ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`78357e5`](https://github.com/ondrasek/agent-container/commit/78357e57375f3b597979984ab44e049b1b755dd7))

### Documentation

- **specs**: Generate tasks for Feature 016
  ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`58ca540`](https://github.com/ondrasek/agent-container/commit/58ca540196f0acfcfb24b32e917d8eb5df2cc6a8))

- **specs**: Record HOW ingestion reads the volume
  ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`8bddd06`](https://github.com/ondrasek/agent-container/commit/8bddd0675d5251536e49672e2dc8562f17bc73ca))

- **specs**: Resolve every analyze finding for Feature 016
  ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`88c4607`](https://github.com/ondrasek/agent-container/commit/88c46073f2ee852337ad8752e49d7c6fe12d75d1))

### Features

- **observability**: Give every run a durable record that outlives its container
  ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`7a92d2b`](https://github.com/ondrasek/agent-container/commit/7a92d2b2431a1c32924ebf07a49ea2571d69a234))


## v0.21.1 (2026-08-09)

### Bug Fixes

- **egress**: Say nothing is enforced when nothing is, and stop the pty probe guessing
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`32dab44`](https://github.com/ondrasek/agent-container/commit/32dab44dca251267a0415a75ebcd676d65e26dd2))

### Chores

- **specs**: Untrack the active-feature pointer
  ([`8102989`](https://github.com/ondrasek/agent-container/commit/8102989211307ed672debc0fbb4a48dd41c73f11))

### Code Style

- Build the inspect template by concatenation
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`2f4c9e9`](https://github.com/ondrasek/agent-container/commit/2f4c9e90af9b7827afce552a8a1584ebbe142315))

### Documentation

- **specs**: Clarify Feature 013 doctor-preflight
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`0b4237a`](https://github.com/ondrasek/agent-container/commit/0b4237a1244840f87ea004053b8431288b61e740))

- **specs**: Clarify Feature 015 kill-switch
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`65522a9`](https://github.com/ondrasek/agent-container/commit/65522a9926a888052dae6ff5363cb3444211038e))

- **specs**: Finish reconciling 012, and mark T138 partial rather than done
  ([`745c67f`](https://github.com/ondrasek/agent-container/commit/745c67f3e810f55015bf10878cbd7d379eb561e0))

- **specs**: Outcomes, retention, identity and reconciliation
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`57fc6d2`](https://github.com/ondrasek/agent-container/commit/57fc6d251361f57acf1af92e5bf70cda0371d0cc))

- **specs**: Reconcile 012's task list with the tree
  ([`b17b726`](https://github.com/ondrasek/agent-container/commit/b17b726c9f2d93323a9c5b9c111d2385b2a9748a))

- **specs**: Run records are a separate store from the inventory
  ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`a6fc7fc`](https://github.com/ondrasek/agent-container/commit/a6fc7fc48e1846424e71e270d7615495c0132e15))

- **specs**: Self-exclusion, a narrower image, and no passphrase recovery
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`58c149e`](https://github.com/ondrasek/agent-container/commit/58c149e7c0c4dab4a8c7266292756e77fe93183a))

- **specs**: Specify Feature 013 doctor-preflight
  ([#013](https://github.com/ondrasek/agent-container/pull/13),
  [`61bacca`](https://github.com/ondrasek/agent-container/commit/61bacca8f9f6a3d0d4bb995e7f5db07176acdc08))

- **specs**: Specify Feature 014 host-inventory
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`77c8b33`](https://github.com/ondrasek/agent-container/commit/77c8b330cb118c6ba5e8f30194592832e86ba5e3))

- **specs**: Specify Feature 015 kill-switch
  ([#015](https://github.com/ondrasek/agent-container/pull/15),
  [`b44092a`](https://github.com/ondrasek/agent-container/commit/b44092ad8f005943907e7331769b5a73e430a274))

- **specs**: Specify Feature 016 run-observability
  ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`3886e8f`](https://github.com/ondrasek/agent-container/commit/3886e8faea80ea3acccda433526417b7faa8563a))

- **specs**: Specify Feature 017 control-plane
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`39bcce6`](https://github.com/ondrasek/agent-container/commit/39bcce6ee35a2b924e01611767b4c902c6b2b55d))

- **specs**: The control plane mints its own key
  ([#017](https://github.com/ondrasek/agent-container/pull/17),
  [`9e66b26`](https://github.com/ondrasek/agent-container/commit/9e66b261c527d244bbacdfc2cc988d79131d64a3))

- **specs**: Two stores, and the inventory needs its own home
  ([#014](https://github.com/ondrasek/agent-container/pull/14),
  [`8c989af`](https://github.com/ondrasek/agent-container/commit/8c989af18967b127be1a25e51a30c7ecdb2831c7))

- **specs**: Who writes the record, and how it learns what changed
  ([#016](https://github.com/ondrasek/agent-container/pull/16),
  [`c562db2`](https://github.com/ondrasek/agent-container/commit/c562db27a7689bcafd0c7a3c95224516a9c1e8a7))

### Testing

- **egress**: Push for real over a declared SSH endpoint, with a control
  ([#012](https://github.com/ondrasek/agent-container/pull/12),
  [`17a0d7d`](https://github.com/ondrasek/agent-container/commit/17a0d7dee577d7a0e20588d77978bafd1891245c))


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

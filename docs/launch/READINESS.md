# AOMS v2 launch readiness audit

## Launch execution record — 2026-08-24

GitHub launch execution completed at `2026-08-24T04:53:49Z` (`2026-08-23
21:53:49 -07:00`). ClawHub publication is prepared but blocked on Dhawal's
account-level acceptance of ClawHub's MIT-0 publishing terms. No social posts
were made; HN/X remain with Dhawal.

| Surface | Final state | Evidence |
|---|---|---|
| Public repository | **SHIPPED** | <https://github.com/dhawalc/cortex-mem> is public, defaults to `main`, shows the v2 README, and uses the description “Local-first scoped memory and recall receipts for MCP agent fleets.” |
| Branch topology | **SHIPPED** | `main` preserves v1 as first-parent history and merges `v2` as a true merge. Release merge `4226a69` has parents `0ee9816` and `581142e`; the CI fix-forward merge is `6720598`. Public `v2` is `451d1d7`. |
| Annotated tag | **SHIPPED** | `v2.0.0` resolves to release merge `4226a69714013584f6f1e970de3774af743a4848`. |
| GitHub release | **SHIPPED** | <https://github.com/dhawalc/cortex-mem/releases/tag/v2.0.0> includes the tag-built wheel, all unfiltered ablations, and canonical `rehearsal-008`. |
| Relay evidence | **REHEARSAL** | Candidate `009` was absent. `rehearsal-008` validated 85 files and passed all 12 verifier checks at `grade=REHEARSAL`; it is explicitly not a final-revision or three-client OpenClaw proof. |
| Ablations | **SHIPPED / REHEARSAL relay grade** | Five complete 36-case eval artifacts and complete scripted memory-enabled/disabled variants are attached; nested and outer manifests validate. |
| Local gates | **PASS** | Corrected release candidate and merged `main`: `193 passed`, one known non-failing Pydantic warning; nested fixture: `3 passed`. |
| GitHub Actions | **PASS after fix-forward 1/3** | [CI](https://github.com/dhawalc/cortex-mem/actions/runs/32691480325) passed Python 3.11, Python 3.12, and clean-wheel acceptance. [Relay fixture](https://github.com/dhawalc/cortex-mem/actions/runs/32691480293) passed. The first CI run exposed missing preserved-v1 test dependencies; commit `451d1d7` fixed only the workflow. |
| ClawHub | **BLOCKED — TERMS** | CLI auth is valid as `DhawalA4`, but publishing v2.0.0 returns “MIT-0 license terms must be accepted.” The package is ready at `packaging/clawhub/aoms`; the live listing remains stale v1.1.0 and must not be launch collateral. |
| Social launch | **DHAWAL** | No HN/X or other social posting was performed. |

### Shipped artifacts

- Wheel: <https://github.com/dhawalc/cortex-mem/releases/download/v2.0.0/cortex_mem-2.0.0-py3-none-any.whl>
- Unfiltered ablations: <https://github.com/dhawalc/cortex-mem/releases/download/v2.0.0/aoms-v2.0.0-unfiltered-ablations.tar.gz>
- Canonical **REHEARSAL** relay bundle: <https://github.com/dhawalc/cortex-mem/releases/download/v2.0.0/aoms-relay-rehearsal-008.tar.gz>
- Published essay: <https://github.com/dhawalc/cortex-mem/blob/v2.0.0/docs/launch/silent-corruption-essay.md>

### Remaining post-launch work

1. **PROOF upgrade:** run with bare provider authentication on a
   bwrap-capable host using Codex `workspace-write`; add working OpenClaw
   provider credentials for the full Claude/Codex/OpenClaw claim.
2. **External reproduction watch:** have a person other than the builder run
   the pinned public instructions on a clean machine and retain exact tag,
   environment, elapsed time, and verifier output.
3. **ClawHub:** Dhawal accepts the MIT-0 publishing terms at
   <https://clawhub.ai/skills/publish>, then reruns the prepared publish command
   recorded below and verifies a fresh v2.0.0 install.
4. **Social posts:** HN/X and other launch posting remain Dhawal's action.

**Audit date:** 2026-08-23 (America/Los_Angeles)

**Audited revision:** `v2` at `3b386778cd305e015bbed375dd7184d24325a345`

**Interpreter:** `/home/dhawal/cortex-mem/cortex-mem/.venv/bin/python`

**Decision:** **LAUNCH AUTHORIZED AT REHEARSAL GRADE**

**Launch override, 2026-08-24:** Dhawal gave the explicit launch order with the
live relay evidence published as **REHEARSAL**, not proof. The two remaining
launch-plan criteria—**PROOF**-grade bare-auth/sandboxed-host evidence and an
external clean-machine reproduction—are now explicit post-launch upgrade/watch
items. This override does not change their status or permit stronger claims.

**Gap-closing update:** The v2.0.0 launch archive now commits all five raw eval
configurations and the complete scripted relay memory-enabled/memory-disabled
ablation at `demo/ablations/v2.0.0`, with a compact table, machine-readable
summary, and SHA-256 manifest. Relay prerequisites and every packaged host
recipe now lead through pinned, bound `setup`; the reviewed v2 ClawHub package
is at `packaging/clawhub/aoms`. The ablation exit criterion below is **PASS**.

This is a launch-gate decision, not a product-quality verdict. The local wheel,
deterministic relay, scope and budget verifier, and canonical test suite work.
The release is authorized with the live artifact explicitly labeled
rehearsal-grade. The public refs, GitHub release, and ClawHub listing still need
to be published during this runbook execution. A different person has not yet
reproduced the public instructions, and the bare-auth/sandboxed-host proof run
remains a post-launch upgrade.

## Source of truth and audit boundary

`docs/LAUNCH_PLAN.md` is not present at the audited revision. Its only repository
version was read with `git show 0ee9816:docs/LAUNCH_PLAN.md`; commit `0ee9816` is
the source of the eight exit criteria below. `docs/launch/FEATURE_GAPS.md` section
3 was read from the audited tree.

All empirical work was read-only against the repository or wrote only to fresh
`/tmp` paths. No live service state, `modules/memory/`, `index/`, restart, real
model run, `~/.local/share/aoms`, or GitHub push was used.

## GO/NO-GO table

| Exit criterion | Status | Empirical evidence | What remains |
|---|---|---|---|
| Clean installer reaches the demo in under 10 minutes | **PASS** for the equivalent local flow | A fresh source copy built a 178 KB `cortex_mem-2.0.0-py3-none-any.whl` in 1.52 s. A fresh `/tmp` venv installed it and all uncached runtime dependencies in 15.48 s. Wheel `setup claude` used an isolated `CLAUDE_CONFIG_DIR`, registered only inside the temporary workspace, materialized the packaged recipe, completed a real MCP handshake and empty scoped recall in 2.20 s, and returned a receipt. `init`, empty recall, `doctor`, and the disposable `tour` also passed without loading a model. The wheel contains 91 paths and none under `service/`, `modules/memory/`, `index/`, `cortex/`, or `cortex_mem/`. | The exact `uvx --from git+...@v2.0.0` route cannot work until the tag is pushed. Repeat the same smoke from the public tag after push. |
| Every agent starts without an upstream transcript | **BLOCKED** for launch-grade proof | `rehearsal-008` has a separately hashed initial prompt and unique session ID for every stage. Claude records `--no-session-persistence`, a new `--session-id`, and strict per-run MCP config; Codex records `--ephemeral --ignore-user-config --ignore-rules` and a private stage workdir. Prompt SHA-256 values reconcile to the captured files and match between memory and baseline variants. | The bundle is correctly graded `REHEARSAL`: Claude used OAuth and explicitly did **not** exclude user-level config; Codex used `danger-full-access` because host `bwrap` isolation was unavailable. It also used Claude/Codex/Claude, not the advertised Claude/Codex/OpenClaw trio, and was produced from `bd134ee`, not the final release revision. A `PROOF` run requires funded bare Claude API access and a bwrap-capable host using `workspace-write`; the full flagship also needs its OpenClaw provider credentials. |
| At least three hidden constraints cross each handoff, each with a valid source | **PASS** at rehearsal grade | Independent verification of `rehearsal-008` passed both stage-2 and stage-3 constraint transmission. The verifier parses only provenance-fenced AOMS JSON blocks, requires packed IDs to exactly equal receipt selections, validates `Provenance`, and checks every declared phrase group. Stage 2 selected all three injected constraint records; stage 3 carried all three constraints through the implementer handoff and also carried the private regression clue. | Repeat on the final tagged code in the `PROOF` bundle; do not present the rehearsal as proof-grade evidence. |
| Serialized recall stays below the declared token ceiling | **PASS** | The sealed rehearsal independently reconciled selected token costs: stage 2 was `632 / 1000`; stage 3 was `829 / 1000`. A new deterministic replay at HEAD passed at `853 / 1000` and `910 / 1000`. | Repeat and publish the values from the final `PROOF` bundle. |
| Out-of-scope canary facts never enter model context | **PASS** | Both rehearsal handoffs passed ID, fact-string, raw-artifact, and serialized-context canary exclusion. Scope-filter counts were 1 at stage 2 and 2 at stage 3. The HEAD deterministic replay also passed both canary checks. | Repeat in the final `PROOF` run. |
| Deterministic repository tests pass | **PASS** | Canonical suite: `187 passed` in 85.79 s with one non-failing Pydantic forward-reference warning. Fixture repository: `3 passed` in 0.01 s. The exact documented scripted relay with `--with-baseline` passed and sealed 91 files in 7.40 s; its independent manifest validation passed. The sealed rehearsal's acceptance verifier also passed durable idempotency, stable equal-timestamp order, and recursive pre-persistence redaction. | CI must repeat this on public `main` for Python 3.11 and 3.12 plus the relay fixture job. The warning is not a gate but should be tracked. |
| Memory-disabled and ablation results are included unfiltered | **PASS** | `demo/ablations/v2.0.0` contains all five complete 36-case eval JSON artifacts plus the sealed 86-file scripted relay with its mirrored memory-disabled baseline. `summary.json` reports `unfiltered=true` and `status=PASS`; `manifest.json` hashes the complete inventory. Expected safety deltas remain visible: no-supersession contradiction rate `0.200`, no-scope canary leakage `0.083`/six selections, and `0.000` for governed configurations. Relay prompts are identical; memory passes 12 checks and baseline retains all three failures. | Publish this already-complete archive with the human-run release push; no further artifact generation is required for this criterion. |
| Another person reproduces the result from public instructions | **BLOCKED**, then **NEEDS-HUMAN** | GitHub reports the repository is already `PUBLIC`, but `origin` has neither `refs/heads/v2` nor `refs/tags/v2.0.0`; public `main` remains at `47c1c8d`. The local tag exists at `7095101`, one commit behind the audited HEAD and before the truth-timeline commands now claimed by README. | First push the final release and corrected tag. Then a person other than the builder must follow the public instructions on a clean machine, record install-to-demo time, run replay and validation, and report the exact commit/tag and result. This cannot be self-certified. |

**Gate count at authorization:** 6 PASS, 2 POST-LAUNCH. The release proceeds
only with the rehearsal grade stated wherever relay evidence is published.

## Rehearsal-008 validation

Bundle: `/home/dhawal/openclaw_archives/aoms-relay-rehearsal-008`

- Manifest SHA-256:
  `4ee172dc7be242e545682bb45478f35bfa66ae656ed13f316c9ee3fe4ee3e469`.
- Seal validation: `valid=true`, 85 files checked, no missing, unexpected,
  size-mismatched, or hash-mismatched files.
- Metadata: scenario `durable-webhook-relay-7319`, seed `7319`, source
  `bd134ee754d808ebf5bfe4c3a258ed90566aac43`, baseline included.
- Agents: planner Claude 2.1.241, implementer Codex CLI 0.145.0, reviewer
  Claude 2.1.241; this is not a three-client OpenClaw proof.
- Independent re-run of `demo.relay_fixture.verify`: passed all 12 checks with
  `grade=REHEARSAL` and no failures.
- Memory-enabled result: pass. Memory-disabled result: fail. The three prompt
  hashes are identical between variants. The baseline has no recall artifacts
  and fails the stable-order acceptance check; this is retained, not hidden.

The bundle is valid and useful rehearsal evidence. It must not be relabeled as a
`PROOF` artifact or described as originating from the final release revision.

## Feature-gaps section 3 finish line

| Feature set | Status at audited HEAD | Launch judgment |
|---|---|---|
| Activation finish line | The wheel-built `setup`, bound identity, packaged recipe, empty-store fast path, real handshake, receipt, importers, and disposable tour all worked in isolation. | Product path passes. Public-tag smoke and documentation alignment remain launch-day work. |
| Recall Observatory | Implemented behind loopback-only `observe`; canonical tests cover it and the current README describes receipt and truth views. | Code is ready. A launch screenshot/static artifact should come from final, synthetic evidence, not a private store. |
| Bring Your Brain | Markdown/Obsidian and fixture-pinned `claude-mem` import paths, preview-first behavior, provenance, scope choice, secret warnings, and idempotency are present and tested. | Code is ready. Public instructions need an external dry-run reproduction. |
| Truth Timeline and Contradiction Inbox | Implemented at `3b38677`, including append-only supersession, `chain`, scope-safe `as_of`, deterministic findings, Observatory rendering, and 328 lines of targeted tests within the passing suite. | HEAD is ready, but the current local `v2.0.0` tag predates this feature. Moving the unpushed tag to the final release commit is mandatory. |

## Hostile-stranger documentation findings

The root README's main activation path is materially better than the old public
draft: it pins a tag, uses `setup`, binds identity, offers a one-memory cold
recall, explains the disposable tour, and makes privacy and scope claims
precisely. All local links from the root README exist.

The remaining problems are launch-significant:

1. The pinned remote tag does not exist, and the same local tag points behind
   the features README claims. Until corrected and pushed, the first command is
   unreproducible.
2. The relay snippet invokes `python -m demo.relay.runner` without first saying
   to clone the repository and install `.[dev]`, or showing an installed/uvx
   equivalent. A stranger who only followed Quick start does not receive a
   `python` environment containing the relay module and dependencies.
3. The packaged `recipes/README.md` and host recipe READMEs still teach manual,
   unpinned `uvx cortex-mem`/bare `cortex-mem` paths and manual configuration.
   That conflicts with the source-correct `cortex-mem setup <host>` path. The
   Claude recipe also says user scope while setup deliberately registers local
   scope. Setup materializes correct bound files, but the included instructions
   can lead a stranger away from them.
4. The essay ends with an unpinned `init` command instead of the reviewed pinned
   `setup` path.
5. The public GitHub repository description still says “persistent 4-tier
   memory,” weighted retrieval, vector search, and progressive disclosure—the
   retired v1 positioning.
6. The public ClawHub `aoms` listing is version 1.1.0 and instructs users to run
   the retired HTTP daemon, JSONL tiers, reinforcement/decay endpoints, Docker,
   `migrate`, and manual OpenClaw boot scripts. The audited repository contains
   no v2 ClawHub skill directory with a `SKILL.md`, so there is currently no
   reviewed asset to publish as version 2.0.0.

Items 1–3 block external reproduction. Items 5–6 would send launch traffic to
false product descriptions and must be corrected before those links are posted.

## Human gates

- **Dhawal essay gate:** `docs/launch/silent-corruption-essay.md` begins with
  “DRAFT FOR DHAWAL'S REVIEW,” is written in Dhawal's first-person voice, and
  explicitly requires his edit and approval. Remove the marker only after he
  verifies every first-person fact, number, date, and attribution.
- **Proof gate:** fund bare provider API access and run on a Linux host where
  Codex `workspace-write`/bwrap works. For the three-client headline, include
  OpenClaw with isolated state and working provider credentials.
- **External gate:** push the final commit and corrected tag, then have a
  different person execute the instructions on a clean machine. Record their
  environment, elapsed time, exact tag SHA, and verifier output.
- **ClawHub gate:** Dhawal reviews `docs/launch/clawhub-skill-v2.md`; then create,
  validate, and publish the v2 package. Do not publish the current v1 listing
  as launch collateral.

## Ordered launch-day runbook

**Trigger word: `LAUNCH`.** Dhawal supplied it on 2026-08-24, approved the essay,
authorized the reviewed ClawHub content, and explicitly deferred the proof host
and external reproduction gates to post-launch.

### A. Freeze the release candidate

- [ ] Work from the audited checkout:

  ```console
  cd /home/dhawal/cortex-mem/aoms-v2
  git switch v2
  git status --short --branch
  ```

- [ ] Dhawal edits and approves the essay; align the relay prerequisites and
  packaged recipe docs; add a reviewed v2 ClawHub skill at
  `packaging/clawhub/aoms/SKILL.md`; update the GitHub-facing copy. Commit these
  changes before proof so the proof's `source_revision` can equal the release.
- [ ] Run the canonical deterministic gates:

  ```console
  AUDIT_TMP="$(mktemp -d /tmp/aoms-v2-release.XXXXXX)"
  PYTHONDONTWRITEBYTECODE=1 /home/dhawal/cortex-mem/cortex-mem/.venv/bin/python \
    -m pytest -p no:cacheprovider --basetemp "$AUDIT_TMP/pytest" -q
  PYTHONDONTWRITEBYTECODE=1 /home/dhawal/cortex-mem/cortex-mem/.venv/bin/python \
    -m pytest -p no:cacheprovider --basetemp "$AUDIT_TMP/fixture-pytest" \
    -q demo/relay_fixture/repository
  ```

- [ ] Generate the complete, unfiltered ablation matrix for the release:

  ```console
  /home/dhawal/cortex-mem/cortex-mem/.venv/bin/python -m aoms.eval run \
    --output-dir "$AUDIT_TMP/aoms-eval-v2.0.0"
  test "$(find "$AUDIT_TMP/aoms-eval-v2.0.0" -maxdepth 1 -type f -name '*.json' | wc -l)" -eq 5
  ```

### B. Produce proof-grade live evidence

- [ ] On the funded, bwrap-capable proof host, with provider secrets supplied by
  its secret manager, run the final three-client bundle:

  ```console
  export AOMS_RELAY_CLAUDE_AUTH=bare
  export AOMS_RELAY_CODEX_SANDBOX=workspace-write
  /home/dhawal/cortex-mem/cortex-mem/.venv/bin/python -m demo.relay.runner run \
    --output /home/dhawal/openclaw_archives/aoms-relay-proof-001 \
    --agents claude,codex,openclaw --seed 7319 --with-baseline
  /home/dhawal/cortex-mem/cortex-mem/.venv/bin/python -m demo.relay.runner validate \
    /home/dhawal/openclaw_archives/aoms-relay-proof-001
  PYTHONDONTWRITEBYTECODE=1 /home/dhawal/cortex-mem/cortex-mem/.venv/bin/python \
    -m demo.relay_fixture.verify \
    /home/dhawal/openclaw_archives/aoms-relay-proof-001
  jq -e '.passed == true and .grade == "PROOF" and (.failures | length) == 0' \
    /home/dhawal/openclaw_archives/aoms-relay-proof-001/verifier/report.json
  ```

- [ ] Confirm the bundle manifest's `source_revision` equals the release
  candidate and `with_baseline` is true. Review the full bundle for publishable
  synthetic-only content; do not publish private prompts or credentials.

### C. Correct the tag, push, and watch CI

- [ ] Confirm the remote tag is still absent, then move the **unpublished local**
  tag from `7095101` to the final release candidate:

  ```console
  test -z "$(git ls-remote --tags origin refs/tags/v2.0.0)"
  git tag -d v2.0.0
  git tag -a v2.0.0 -m "AOMS v2.0.0 — scoped memory for agent fleets"
  RELEASE_SHA="$(git rev-parse HEAD)"
  test "$(git rev-parse v2.0.0^{})" = "$RELEASE_SHA"
  git status --porcelain
  ```

- [ ] Push the release commit to both public `main` and `v2` (the audited remote
  `main` is an ancestor, so this is a fast-forward), but hold the tag until CI:

  ```console
  git push --atomic origin HEAD:main HEAD:v2
  ```

- [ ] Watch both required workflows for the exact release SHA:

  ```console
  RELEASE_SHA="$(git rev-parse HEAD)"
  CI_RUN="$(gh run list --repo dhawalc/cortex-mem --workflow ci.yml \
    --commit "$RELEASE_SHA" --limit 1 --json databaseId --jq '.[0].databaseId')"
  RELAY_RUN="$(gh run list --repo dhawalc/cortex-mem --workflow relay-fixture.yml \
    --commit "$RELEASE_SHA" --limit 1 --json databaseId --jq '.[0].databaseId')"
  test -n "$CI_RUN" && gh run watch --repo dhawalc/cortex-mem "$CI_RUN" --exit-status
  test -n "$RELAY_RUN" && gh run watch --repo dhawalc/cortex-mem "$RELAY_RUN" --exit-status
  ```

- [ ] Only after both workflows pass, publish the tag:

  ```console
  git push origin refs/tags/v2.0.0
  ```

### D. Confirm public state and external reproduction

- [ ] The repo is already public; verify rather than toggling it:

  ```console
  test "$(gh repo view dhawalc/cortex-mem --json visibility --jq .visibility)" = PUBLIC
  ```

- [ ] Replace the stale v1 repository description:

  ```console
  gh repo edit dhawalc/cortex-mem \
    --description "Local-first scoped memory and recall receipts for MCP agent fleets"
  ```

- [ ] On a clean external machine, have a person other than the builder run the
  pinned README quick start and timed disposable tour, then the documented relay
  replay and validator. They must confirm `v2.0.0` resolves to `$RELEASE_SHA`,
  setup-to-demo is under 10 minutes, the manifest validates, and the verifier
  passes. Save their commands and output as release evidence.

### E. Publish release evidence and ClawHub

- [ ] For this rehearsal-grade launch, archive canonical `rehearsal-008` and the
  complete ablation directory, then create the GitHub release from the verified
  tag. Label the relay attachment **REHEARSAL** and state the **PROOF** upgrade
  path (bare provider auth plus a bwrap-capable sandboxed host):

  ```console
  REHEARSAL_TGZ=/tmp/aoms-relay-rehearsal-008.tar.gz
  EVAL_TGZ=/tmp/aoms-eval-v2.0.0.tar.gz
  tar -C /home/dhawal/openclaw_archives -czf "$REHEARSAL_TGZ" aoms-relay-rehearsal-008
  tar -C demo/ablations -czf "$EVAL_TGZ" v2.0.0
  gh release create v2.0.0 --repo dhawalc/cortex-mem --verify-tag \
    --title "AOMS v2.0.0" --generate-notes \
    "$REHEARSAL_TGZ#REHEARSAL-grade relay bundle" \
    "$EVAL_TGZ#Unfiltered retrieval ablations"
  ```

- [ ] Publish the reviewed v2 ClawHub package, never the installed v1.1.0
  content:

  ```console
  clawhub publish packaging/clawhub/aoms --slug aoms \
    --name "AOMS — Scoped Memory for Agent Fleets" --version 2.0.0 \
    --changelog "Scoped MCP memory, receipts, local SQLite, activation, importers, and relay rehearsal evidence" \
    --tags latest,v2
  ```

- [ ] Install the listing into a fresh temporary directory and reject it if any
  retired-v1 phrases remain:

  ```console
  CLAWHUB_CHECK="$(mktemp -d /tmp/aoms-clawhub-v2.XXXXXX)"
  clawhub --workdir "$CLAWHUB_CHECK" --dir skills install aoms
  ! rg -n 'cortex-mem start|/memory/decay|JSONL files|4-tier|ChromaDB|cortex-mem migrate' \
    "$CLAWHUB_CHECK/skills/aoms"
  ```

### F. Post only immutable, verified links

- [ ] Repository/hero link: <https://github.com/dhawalc/cortex-mem>
- [ ] Release, **REHEARSAL** bundle, and ablations:
  <https://github.com/dhawalc/cortex-mem/releases/tag/v2.0.0>
- [ ] Dhawal-approved incident essay:
  <https://github.com/dhawalc/cortex-mem/blob/v2.0.0/docs/launch/silent-corruption-essay.md>
- [ ] Relay protocol and reproduction:
  <https://github.com/dhawalc/cortex-mem/blob/v2.0.0/demo/relay/README.md>
- [ ] Corrected ClawHub listing:
  <https://clawhub.ai/dhawala4/skills/aoms>
- [ ] Post in this order: GitHub release/README, technical essay, relay rehearsal,
  ClawHub listing. Use the immutable tag links in X, LinkedIn, and any Show HN
  submission; do not call rehearsal evidence proof.

## Residual concerns after the blockers clear

- The fresh install is fast on this host, but the uncached runtime dependency
  set is still substantial because FastEmbed pulls ONNX, NumPy, Hugging Face,
  and tokenizers even when the empty-store path does not load a model.
- The single Pydantic `IncompleteFieldDefinitionWarning` in MCP parity tests did
  not affect results, but warning-free launch CI would make failures easier to
  notice.
- `rehearsal-008` is sealed correctly, but its absolute build paths refer to a
  temporary archive staging directory. This is acceptable evidence, not a
  portable command path.
- Do not let a successful deterministic scripted replay substitute for the live
  three-client proof. Scripted replay proves protocol determinism; the live
  bundle proves client interoperability and transcript isolation.

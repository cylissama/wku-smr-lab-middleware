# CI/CD for the edge images (IMU + camera)

Source notes: `plans/11-16-26-cidi.md` (2026-11-16).
Branch for the AMS-side work: `dev/edge-cicd` (off `main`). The edge repos get
their own branches/PRs (see Phase 1).

## Goal

1. A push to the IMU and camera repos' default branches builds and publishes
   the edge image automatically, so there is always a current image for each
   service type.
2. The Swarm stack deploys those published images instead of whatever was
   built by hand on each Pi.
3. Getting a new image onto the Pis needs no SSH, and never happens in the
   middle of a session.

## Current state (checked 2026-11-16)

| | IMU | Camera |
| --- | --- | --- |
| Repo | `cylissama/wku-smr-lab-imu-edge-node` (public) | `UmarKhattab09/wku-smr-lab-camera-edge-node` (public; we have WRITE, not admin) |
| Default branch | `main` | `master` |
| Branch the Pis run | `plc_update` (5 commits ahead of `main`, 0 behind) | unknown: `master` (`plc_update` is 3 behind it) plus the unmerged remote-processing patch `plans/camera-offload/0001-camera_edge-remote-processing.patch` (`frame_forwarder.py` is not on any branch) |
| Dockerfile | `Dockerfile` at repo root, context `.` | `camera-swarm-fusion/camera_edge/Dockerfile`, context `camera-swarm-fusion/` |
| Base image | `python:3.11-slim` | `python:3.11-slim` + `libgl1 libglib2.0-0`, opencv-contrib-headless |
| CI | none (no `.github/`) | none |
| Image in the stack file | `smart-mfg-imu:latest` (local tag, built on each Pi) | `camera-edge:latest` (local tag, built on each Pi) |
| Pi paths | `/opt/smart-mfg-imu` | `/opt/camera-sensor-fusion` |

- Swarm: manager `AMS` (x86_64). Workers RPIIMUJ1–J6 and RPICAM1–4, **all
  aarch64, Docker 29.9.x** (J6 29.9.2). So one `linux/arm64` image per type is
  enough. The comment in `deploy/swarm-edge-nodes.yml` that RPIIMUJ3 runs
  Docker 20.10 is stale.
- Node labels: cameras have `camera=cam1..cam4`; IMUs have none (placed by
  hostname).
- Today's update procedure: on each Pi, `git pull` + `docker build -t <tag> .`.
  Ten Pis, by hand. The swarm-nodes doc still has a TODO for that exact command
  (`web/docs/expanding/swarm-nodes.md` §3) and `overview/repositories.md` has
  two TODOs about images.
- Every deploy goes through stack-controller with
  `deploy_flags: ["--resolve-image", "never"]` (`stack_controller/stacks.yml`).
  The edge stack is deployed on **every** Start Monitoring / Start Session and
  removed on Stop (except Keep edge running standby). So anything a deploy
  does (registry lookups, pulls) lands on the session-start path that
  "Edge ready" measures.
- The gh token on the AMS is a fine-grained PAT: `git push` to this repo works,
  `gh pr create` doesn't (memory `gh-token-no-pr`). It probably can't push
  `.github/workflows/*` either (needs the "Workflows" permission) and may not
  have access to the camera repo at all. Expect to hand workflow files to the
  user.

## The `:latest` question: pinned digests, promoted from the AMS

The notes ask whether to let each Pi look for new versions itself, or to put
`image: something:latest` in the stack file and let Swarm resolve it. Neither,
for this lab:

| Option | Problem here |
| --- | --- |
| Auto-pull agent on each Pi (Watchtower or similar) | Watchtower replaces containers itself, outside Swarm, so Swarm and the agent fight over the same task. It would also update in the middle of a recording. |
| `:latest` + `--resolve-image always` | The manager queries the registry on **every** deploy, so every session start depends on GHCR and internet latency. Workers pull the new image during session start, so the first session after a push waits for 10 Pis to download it and "Edge ready" jumps. Whatever was pushed to `main` reaches the cell untested, and nothing records which code produced a session's data. |
| `:latest` + `--resolve-image never` (today's flag) | Not reproducible: "latest" means whatever that Pi last pulled, so Pis can silently run different builds. |

**Recommended:** CI publishes immutable tags (`sha-<short>`) plus a moving
`latest`. The AMS deploys a **pinned reference** (tag + digest, e.g.
`ghcr.io/cylissama/wku-smr-lab-imu-edge-node:sha-1a2b3c4@sha256:…`) taken from
`deploy/.env`. A new build reaches the Pis in two explicit steps run from the
AMS, refused while recording:

1. **Pre-pull**: a short-lived Swarm job puts the image on every IMU (or
   camera) Pi ahead of time.
2. **Promote**: write the new reference into `deploy/.env`. The next
   Start Monitoring / Start Session deploys it with no download.

With a digest-pinned image already on the node, a deploy contacts no registry,
so session starts stay as fast as today. Rolling back means putting the old
reference back in `.env` (the old image is still on the Pis). The reference
can be stored per session, so each session records which edge code produced
its data.

"Auto pull" is then a **check**: the AMS compares the promoted digest with the
registry's `latest` and reports "update available" (CLI first, dashboard
later). It can optionally pre-pull on its own. Promotion stays a human step.

## Decisions for the user (defaults in bold; ask before Phase 1)

1. Registry: **GHCR** (`ghcr.io/<owner>/<repo>`, free for public repos, CI
   authenticates with `GITHUB_TOKEN`) vs Cy's Docker Hub account (needs a Hub
   token stored as a secret in both repos, and anonymous pulls are rate
   limited).
2. Camera package owner: **`ghcr.io/umarkhattab09/...`** (the repo's own
   namespace, the simplest option; making the package public needs Umar, the repo
   owner) vs moving or forking the camera repo under `cylissama`.
3. Branch the CI builds: the default branches (`main` / `master`) as the notes
   say. That requires **merging IMU `plc_update` into `main` and the
   camera-offload patch into `master` first** (Phase 1). Otherwise the first CI
   image would lose the PLC trigger (IMU) or remote processing (camera).
4. Promotion: **manual** (CLI, later a dashboard button) vs automatic
   promotion of every `main` build while IDLE.
5. Pre-pull: **manual** (with the promotion) vs an AMS timer that pre-pulls a
   new `latest` automatically (never while recording).

## Phase 0: Inventory and a pull-behaviour spike (no code changes)

1. On each Pi, record what it runs now. The user may have to run this over
   SSH; IMU Pis use `/opt/smart-mfg-imu`, camera Pis use
   `/opt/camera-sensor-fusion`:
   `git -C <path> rev-parse --abbrev-ref HEAD; git -C <path> log -1 --oneline; git -C <path> status --short; docker image inspect <tag> --format '{{.Id}} {{.Created}}'`.
   Note any Pi with uncommitted local changes. Those changes must be
   committed upstream before CI images replace the local builds.
2. Confirm each Pi can reach `ghcr.io` (`docker pull ghcr.io/library/hello-world`
   or `curl -sI https://ghcr.io/v2/`).
3. Spike on **one** IMU Pi with a throwaway image (push any small arm64
   image to GHCR by hand, or use a public one by digest). Verify with Docker
   29 that:
   - a service whose image is `name:tag@sha256:…` and **already present** on
     the node starts **without contacting the registry**, under
     `--resolve-image never` (watch `docker events` / daemon log on the Pi,
     time task start with the Pi's network unplugged from the internet if
     practical);
   - a service whose image is a local-only tag (today's `smart-mfg-imu:latest`)
     makes a failed pull attempt first, and how long that takes. It may be
     part of today's start latency;
   - `docker service create --mode global-job --constraint node.labels.edge==imu --restart-condition none <ref> true`
     leaves the image on every matching node, and the job's task states
     show per-node success or failure.
   Write the results into this plan before Phase 3. If digest-pinned images
   still trigger a pull, look at the daemon's `DOCKER_SERVICE_PREFER_OFFLINE_IMAGE=1`
   environment variable on the Pis as the fallback, and record which one is
   used.

## Phase 1: Edge repos are ready to build from their default branches

Do this in the edge repos, not here. Use PRs; the user merges.

1. IMU: PR `plc_update` → `main` (fast-forward; it's 5 ahead, 0 behind).
   Pull in any Pi-local changes found in Phase 0.
2. Camera: PR into `master` with the camera-offload patch (`git am
   plans/camera-offload/0001-camera_edge-remote-processing.patch` on a branch
   off `master`), plus any Pi-local changes. Re-run the checks listed in
   `plans/camera-offload-plan.md` (remote mode with a real Mosquitto).
   Note: `camera_processor/protocol.py` here and `camera_edge/frame_forwarder.py`
   there must stay in sync (CLAUDE.md).
3. Add a `.dockerignore` to each repo if missing (`.git`, `data/`, `__pycache__`,
   `*.csv`, saved frames), so CI and local builds don't bake in run data.
   Check that the camera image still includes `calib/`
   (`CAMERA_CAM<N>_CALIBRATION_PATH` points into it).

## Phase 2: GitHub Actions build and publish

One workflow per edge repo, `.github/workflows/image.yml`:

- Triggers: `push` to the default branch (`main` / `master`), tags `v*`,
  `workflow_dispatch`. `pull_request` builds without pushing, as a check.
- Runner: `ubuntu-24.04-arm` (native arm64, free for public repos), so no QEMU.
  Platform `linux/arm64` only (every node is aarch64).
- Steps: `actions/checkout`, `docker/setup-buildx-action`,
  `docker/login-action` to `ghcr.io` with `GITHUB_TOKEN` (permissions:
  `contents: read`, `packages: write`), `docker/metadata-action`, and
  `docker/build-push-action` with `cache-from/to: type=gha`.
  Use current major versions of each action, pinned.
- Tags: `sha-<7>`, `latest` (default branch only), `<branch>`, and `vX.Y.Z` for
  git tags. Labels: OCI `org.opencontainers.image.source` (links the package
  to the repo), `.revision`, `.created`.
- Image names (lowercase): `ghcr.io/cylissama/wku-smr-lab-imu-edge-node`,
  `ghcr.io/umarkhattab09/wku-smr-lab-camera-edge-node` (or what decision 2
  picks).
- Camera context: `camera-swarm-fusion`, file
  `camera-swarm-fusion/camera_edge/Dockerfile`.
- Job summary: print the pushed digest and the full `name:sha-x@sha256:…`
  reference, so promoting is a copy-paste.
- Tests (optional, non-blocking at first): IMU's unit tests if any; the camera
  pytest suite has 13 known failures, so run it with `continue-on-error` until
  they're fixed.

After the first successful run, set each package's visibility to **Public**
in the GitHub package settings. This needs the package owner: Cy for IMU,
Umar for camera unless decision 2 changes it. Public packages let the Pis pull
anonymously, so no registry credentials go into the Swarm.

The workflow files likely need the user to push them (PAT scope; see Current
state). Prepare them in the scratchpad or as patch files under
`plans/edge-cicd/` and hand over.

Acceptance: a push to each default branch produces an arm64 image on GHCR, and
`docker manifest inspect <ref>` works from the AMS without logging in.

## Phase 3: Stack file and `.env` use pinned published images

AMS repo, `dev/edge-cicd`.

1. `deploy/swarm-edge-nodes.yml`: `image: ${IMU_IMAGE:-smart-mfg-imu:latest}` on
   the six IMU services and `image: ${CAMERA_IMAGE:-camera-edge:latest}` on the
   four camera services. The fallback keeps today's behaviour until `.env` sets
   them. Fix the stale Docker 20.10 comment.
2. `deploy/.env.example` (and `deploy/.env` on prod): add `IMU_IMAGE` and
   `CAMERA_IMAGE` with a comment explaining the pinned `name:sha-x@sha256:…`
   format and pointing at the promote command. Don't add them to
   `env_overrides` in `stack_controller/stacks.yml`. They're infrastructure,
   so the dashboard must not set them.
3. Keep `deploy_flags: ["--resolve-image", "never"]`, or change it based on the
   Phase 0 spike, and update the comment in `stacks.yml` to say why.
4. Node labels so jobs can target one device type:
   `docker node update --label-add edge=imu RPIIMUJ<n>` (×6) and
   `--label-add edge=camera RPICAM<n>` (×4). Keep the existing `camera=camN`
   labels; placement still uses them and the hostnames. Add the label step
   to the new-Pi checklist in `web/docs/expanding/swarm-nodes.md`.
5. Check `stack_controller/docker_ops.get_stack_status`'s `_spec_key`
   (image is part of the task spec key, used to ignore tasks from an older
   deploy). A digest-pinned image string must compare equal across deploys
   of the same reference. Add a test if the string Swarm stores differs from
   the one we pass (Swarm may append or normalise the digest).
6. Tests: `tests/` already checks stack-file things (architecture labels,
   `env_overrides` vs run params). Add a check that every edge service's
   `image:` is `${IMU_IMAGE…}` / `${CAMERA_IMAGE…}`, so nobody hard-codes a tag
   again.

Acceptance: with `IMU_IMAGE`/`CAMERA_IMAGE` unset, a deploy is byte-for-byte
today's behaviour. With them set to a pre-pulled reference, Start Monitoring
reaches "Edge ready" in about the same time as before (compare with the 3–11 s
baseline in `plans/keep-edge-running-plan.md`).

## Phase 4: `edge-images` tool on the AMS (check, pre-pull, promote, status)

The Swarm calls belong in stack-controller, since it holds the Docker
socket and is the only deploy agent. The first cut can be a CLI script so it
can be tested before any API exists. Suggested shape:

`deploy/edge_images.py` (stdlib only; run on the AMS host, or later imported
by stack-controller):

- `check`: for each type, read the reference in `deploy/.env` and fetch the
  registry's current `latest` digest (anonymous GHCR token:
  `GET https://ghcr.io/token?scope=repository:<owner>/<repo>:pull`, then
  `HEAD /v2/<owner>/<repo>/manifests/latest` with the OCI/Docker manifest
  `Accept` headers, read `Docker-Content-Digest`). Print "up to date" or
  "update available: sha-x (built …)".
- `prepull <imu|camera> [ref]`: refuse unless fastapi-app's `GET /capture`
  says `IDLE` (or `MONITOR` without recording, decide: a pull competes with
  camera frames for the 192.168.2.x link, so IDLE only is the safe default).
  Run `docker service create --detach --mode global-job --constraint
  node.labels.edge==<type> --restart-condition none --name prepull-<type>-<sha> <ref> true`.
  The image's CMD is replaced by `true`; if the image has no `true` binary,
  use `python3 -c pass`. Wait, report per-node task state, then remove the
  job service. Nodes that are `Down` are listed as skipped, not failed.
- `promote <imu|camera> <ref>`: refuse unless IDLE (in MONITOR/standby the
  running stack would keep the old image, and `deployed_env` wouldn't notice).
  Refuse if the last pre-pull of that ref didn't succeed on every Ready node
  of that type, unless `--force`. Rewrite the one line in `deploy/.env` in
  place: don't regenerate the file, and note that stack-controller reads it
  through a bind mount, so an editor that replaces the file can leave the
  container with a stale copy (`web/docs/docker/stack-controller.md`).
  Keep the previous value as a comment (`# previous: …`) for rollback.
- `status`: per node, which tagged versions of the edge image are present
  (another global-job can't easily report this; use `docker service ps` of the
  last pre-pull, or skip until Phase 5).
- `rollback <imu|camera>`: swap to the `# previous:` reference.

Docs: new page `web/docs/docker/edge-images.md` (how CI builds, how to
check/pre-pull/promote/roll back, what to do when a Pi was Down during the
pre-pull). Link it from `docker/swarm.md`, `expanding/swarm-nodes.md`
(replace the §3 TODO: "nothing to build on the Pi; the image is pulled by
pre-pull"), and `overview/repositories.md` (replace both image TODOs and
the stale Docker Hub section). Add it to `web/docs/.vitepress/config.ts`.

Acceptance: from a clean IDLE state on prod, push a trivial change to the IMU
repo. Then `check` shows an update, `prepull imu` puts it on J1–J6,
`promote imu` updates `.env`, and the next Start Monitoring runs the new
digest on every IMU (`docker service ps edge_imu-106 --no-trunc` shows it) with
normal "Edge ready" timing. `rollback imu` restores the old one the same way.

## Phase 5 (optional): Dashboard and session provenance

1. stack-controller endpoints, wrapping Phase 4: `GET /images` (promoted vs
   registry latest, per type) and `POST /images/{type}/prepull`. Add
   `POST /images/{type}/promote` only if decision 4 allows it from the
   dashboard. fastapi-app proxies them under `session_lock`, refused outside
   IDLE (same pattern as `PUT /parameters`).
2. Dashboard: a small "Edge images" box (current `sha-x` per type, "update
   available", Pre-pull and Promote buttons with the same refusals).
3. Provenance: store the deployed edge image references per session. Either
   a new `session.edge_images` JSONB column (migration entry in
   `db/migrations.md`, `db/schema.sql`, `db/database.py`) or alongside
   `session.parameters`. The new column is cleaner, since `parameters` is
   specifically run parameters. Show it on the session detail.
4. Optional auto pre-pull (decision 5): a background task in stack-controller
   or fastapi-app that runs `check` every N minutes and pre-pulls a new `latest`
   while IDLE. Promotion stays manual unless decision 4 says otherwise.
5. Cleanup of old images on the Pis (SD cards): a global-job using a
   `docker:cli` image with the socket bind-mounted that removes that repo's
   images **except the promoted and previous references**. Never use
   `docker image prune -a`: with the edge stack down, the current image is
   unused and would be deleted.

## Out of scope

- The AMS's own images (fastapi-app, tcp, web, camera-processor,
  stack-controller) stay built on the AMS with `docker compose build`. They
  could get the same CI later, but they're one host and the user runs those
  recreates.
- `imu_host` / `camera_host` (systemd on the Pis, outside Docker) still update
  by `git pull` on each Pi. Note this in the new docs page. Changes that
  touch both sides (socket protocol) need both updated together.
- A local registry or pull-through cache on the AMS. Daemon `registry-mirrors`
  only apply to Docker Hub, so a GHCR cache would mean retagging to the AMS
  registry and configuring `insecure-registries` on 10 Pis. Not worth it
  unless Phase 0 shows that internet pulls are too slow.

## Risks and rollback

- **First CI image differs from what the Pis run** (unmerged branches, local
  edits). Mitigated by Phase 0 inventory + Phase 1 merges. Until `IMU_IMAGE` /
  `CAMERA_IMAGE` are set, nothing changes on the Pis.
- **A Pi is Down during pre-pull**, then comes back and gets scheduled: it pulls
  at session start, which is slow but works because the image is public. `promote`
  warns about it; re-run `prepull` once the Pi is up.
- **GHCR or internet down**: pinned, pre-pulled images keep working. Only
  `check`/`prepull` fail.
- **Rollback of the whole change**: unset `IMU_IMAGE`/`CAMERA_IMAGE` in
  `deploy/.env`. The stack falls back to the local `smart-mfg-imu:latest` /
  `camera-edge:latest`, as long as those local images are left on the Pis
  (don't clean them up until the new flow has run several sessions).

## Steps and commits (commit after each, per memory `commit-each-step`)

1. Plan (this file).
2. Phase 0 inventory + spike results written into this plan.
3. Phase 1 PRs in both edge repos (user merges).
4. Phase 2 workflows (user pushes if the PAT can't); first images on GHCR,
   made public.
5. Phase 3 stack file, `.env.example`, node labels, tests.
6. Phase 4 `deploy/edge_images.py` + docs. Prod test (IMU first, then camera),
   user runs any container recreates.
7. CLAUDE.md: replace the "built on each Pi" notes with the pinned-image flow
   (Architecture → two deployment surfaces) and add the `edge_images` commands.
8. Phase 5 if wanted.

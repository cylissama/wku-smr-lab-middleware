# Progress log

Where work stands, so the next session can pick up. Newest first. Detailed design and as-built notes live in each plan file; this is only the handoff.

## 2026-10-27

### Interactive architecture diagram (`plans/interactive-architecture-plan.md`)

**Status:** phases 1 and 2 done, committed and deployed. **Next: phase 3.**

- Branch `dev/architecture-diagram`, not pushed. It was branched from `dev/device-graphics`, so it also carries that branch's 3 unmerged commits (`45f17b7`, `93d7831`, `ed4e035`).
- Commits `f428002` … `d0da7a9`, one per step (plan, workspace, model, views, hosting, docs links, labels, generator, test, workflow notes).
- **Live:** `http://192.168.2.100/architecture/`. The running `web` container is the phase 2 image. Rollback image `wku-smr-lab-middleware-web:pre-architecture` (from before phase 1).
- **What exists:**
  - `web/architecture/`: LikeC4 1.60.0 workspace. `spec.c4`; `model/{landscape,ams,edge,connections}.c4` (hand-written); `views/static.c4` (landscape, robot cell, AMS host, fastapi internals, web, edge, IMU node, camera node, NAS, downstream, "Needs details"); `views/deployment.c4` (machines view); `generated/{inventory,edge-hosts}.c4`.
  - `architecture/sync.py` regenerates `generated/` from `docker-compose.yml` and `deploy/swarm-edge-nodes.yml` (`smr.description` labels). `tests/architecture_test.py` fails when that's stale.
  - `web/scripts/build-architecture.sh` runs in the web image build. An invalid model logs an error and publishes an error page; it never fails the build (user decision).
  - npm scripts in `web/`: `arch:dev`, `arch:check`, `arch:build`.

**Phase 3 to do** (flows + docs):
1. Add dynamic views in `web/architecture/views/flows.c4`: IMU sample → DB, robot line → DB, Start Monitoring / Start Session (deploy through stack-controller), PLC stop → drain → backup, live updates to the dashboard (`/ws/*`), health and watchdog. Syntax reference: `web/node_modules/likec4/skills/likec4-dsl/references/dynamic-views.md`.
2. Embed views in the docs with the web component the build already produces (`/architecture/likec4-views.js`, `<likec4-view view-id="…">`). Replace the PNGs in `web/docs/overview/structure.md` (`diagram-1-ingestion.png`, `diagram-2-live-and-backups.png`, `diagram-4-web-frontends.png`). VitePress needs `likec4-*` treated as custom elements (`vue.template.compilerOptions.isCustomElement` in `docs/.vitepress/config.ts`).
3. Write a new docs page, "Keeping the architecture current": the label → `sync.py` → test workflow, where hand-written parts go, `npm run arch:dev`. Also add a line to `web/docs/expanding/index.md` ("A container on the AMS host": set `smr.description`, run `sync.py`).
4. Then phase 4 (freshness: `reviewed`/`paths` metadata, `sync.py --status`, `#changed-since-review`).

**Open questions for the user:**
- What the image analysis machine, digital twin and AI service are, and who owns them. They're `#placeholder` elements; see the "Needs details" view.
- The camera host service that provides `/run/camera-hw`, the IMU sensor and camera models, and which machines sync from the `ntp` container. These are TODOs in element descriptions.

**Gotchas found:**
- `likec4` needs Node ≥ 22 (the web builder is `node:22-alpine` now) and `--no-use-dot` on Alpine (no Graphviz binary).
- `extend` can add children, links, metadata and relationships, but not titles or descriptions.
- `**` in a view only includes connected descendants. `cell.*.*` is invalid; list `<net>.<host>.*` instead.
- VitePress prefixes `/docs/` onto nav links; the nav uses `/../architecture/`.
- Code links point at `main`, so `fast_server/run_params.py` 404s until this branch merges.
- Next full `docker compose up -d` recreates every AMS service (labels changed). Do it while nothing is recording.

**How to check things on this host** (no Node or Python deps installed):
- LikeC4: `docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -v $PWD/web:/app -w /app node:22-alpine npx likec4 validate architecture`
- Tests: `docker run --rm -v $PWD:/repo:ro -w /repo --entrypoint python smr-test -m unittest tests.architecture_test` (use `-p "*_test.py"` with `discover`; 15 failures in backup/parse/sessions/tcp tests predate this work)
- Screenshots: `mcr.microsoft.com/playwright/python:v1.49.0-jammy` + `pip install playwright==1.49.0`, against the site served from a throwaway `web` container on port 18081

### Uncommitted work in the tree (not part of the branch's commits)

- **Docs update** (`plans/docs-update.md`): rewritten and new pages under `web/docs/` (api, plc, capture-modes, dashboard, the troubleshooting additions, …), plus `plans/` moves into `completed/` and path fixes in `CLAUDE.md`, `common/log_schema.py`, `fast_server/health.py`, `stack_controller/containers.py`. Finished and deployed in the web image, **waiting for the user's OK to commit**. Its open TODOs are marked `::: info Placeholder` in the pages.
- **Camera PLC trigger env** (`CAMERA_PLC_*`) in `deploy/swarm-edge-nodes.yml`: the user's own edit. Leave it alone unless asked.

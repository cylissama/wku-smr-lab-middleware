# Interactive architecture diagram: plan

Request: `plans/interactive-architecture.md`. Status: **phase 1 in progress** (2026-10-27).

**Decided:** LikeC4; hosted at `/architecture/`; an invalid model does **not** fail the web image build (it logs an error and the page shows it); phase 5 skipped for now; downstream consumers are placeholders. Still open: `smr.description` labels (phase 2).

## 1. What we're building

One architecture model, stored as text in this repo. It renders as a clickable, zoomable website at `http://192.168.2.100/architecture/`. It shows:

- **The boundaries:** robot cell, edge Pis, AMS host, NAS, and downstream consumers, with every service inside them.
- **The pipelines between them:** protocol, port and topic on each arrow (MQTT `imu/#`, robot CSV over TCP 5001, EtherNet/IP to the PLC, SQL to the NAS, …).
- **Clickable elements:** each one links to its code (GitHub path, in whichever repo it lives) and its docs page. Each has drill-down views (landscape → AMS host → fastapi-app internals).
- **Step-by-step flows:** "an IMU sample reaches the database", "Start Session deploys the edge", "a PLC pulse stops the session".
- **What's out of date:** elements whose code has changed since someone last reviewed their part of the diagram are highlighted. The service inventory can't silently fall behind `docker-compose.yml` and `deploy/swarm-edge-nodes.yml`, because a test fails.

The current PNGs (`web/docs/overview/diagram-*.png`) are hand-drawn and already partly wrong. `diagram-3-deployment.png` was deleted in the docs update for that reason. They get replaced by live views from the same model.

## 2. Research: what people use for this

| Option | What it is | Fit here |
| --- | --- | --- |
| **LikeC4** (MIT, v1.60.0, Oct 2026) | DSL for C4-style models → interactive static site, React components or web components. Has a VS Code extension with live preview, `validate`, `export json`, a TS model API, dynamic (sequence) views and a deployment model. | **Best fit.** Text in git, interactive out of the box, builds with the Vite/Node toolchain `web/` already uses, embeds in VitePress as a web component. |
| Structurizr DSL | The original "C4 model as code" tool (Simon Brown). Strict C4 rules, exports to PlantUML/Mermaid. | Strong modelling, weaker web output. The interactive viewer is a Java server (Structurizr Lite/on-prem): one more container to run. |
| IcePanel | Hosted drag-and-drop C4 modelling with collaboration. | Not code: the model lives in a SaaS, outside git, and can't be checked against the repo. Paid for teams. |
| D2 / Mermaid | Text → diagram renderers. | Good for single pictures, but no model: each diagram repeats the same facts, so they drift apart. Mermaid C4 is static. |
| Custom JSON + React Flow (`@xyflow/react`) | Write our own schema and canvas in the dashboard. | Full control and easy live overlays, but we'd build and maintain layout, drill-down, flows and validation ourselves. LikeC4's diagram component is itself built on React Flow. |
| Backstage software catalog | `catalog-info.yaml` per component, with a dependency graph. | Built for orgs with many teams and services; far too heavy for one lab. |

There's no ready-made tool that diffs a model against `docker-compose.yml`. The usual pattern, which we'll use, is **generate the inventory from the deploy files, hand-write the meaning, and fail a check when they disagree.**

### Things I verified on this host

- `extend <element> { … }` in a hand-written file can add **tags, links, metadata, child elements and relationships** to an element defined in a generated file. It can't change its title or description. `validate` passes, and `export json` shows the merged result. This decides the file split in §3.2.
- `likec4 build --no-use-dot --base /architecture/` works on `node:22-alpine` (WASM Graphviz; the default needs a `dot` binary that Alpine lacks). Output: a 5.6 MB static site, plus `likec4-views.js` web components for embedding.
- LikeC4 1.60 requires **Node ≥ 22**; `web/dockerfile` builds on `node:20-alpine`. Vite 7 and VitePress 1.6 run fine on 22.
- Useful CLI commands: `likec4 start` (live preview), `validate`, `build`, `export json|png|drawio|markdown`, `gen webcomponent|react|mermaid|d2`.

## 3. Design

### 3.1 Files

```text
web/architecture/                 # LikeC4 workspace (inside web/ so the web image's build context has it)
├── likec4.config.json            # project name, title
├── spec.c4                       # element kinds (zone, host, service, device, person, repo), tags, styles
├── model/
│   ├── landscape.c4              # people, robot cell, PLC, NAS, downstream consumers (hand-written)
│   ├── ams.c4                    # extend generated AMS services: relationships, children, links, review metadata
│   └── edge.c4                   # extend generated edge services: MQTT, PLC reads, imu_host on the Pi
├── views/
│   ├── static.c4                 # landscape, per-zone, per-service views
│   ├── flows.c4                  # dynamic views (the step-by-step pipelines)
│   └── deployment.c4             # hosts, IPs, Swarm placement
└── generated/                    # written by architecture/sync.py, never edited by hand
    ├── inventory.c4              # one element per Compose/Swarm service
    └── status.c4                 # freshness tags (see 3.4)
architecture/sync.py              # repo root: reads the deploy files, writes web/architecture/generated/
tests/architecture_test.py        # inventory is current; every service is described
```

### 3.2 What's generated vs. hand-written

**Generated** by `architecture/sync.py` (plain Python + PyYAML, already a dependency):

| Source | Becomes |
| --- | --- |
| `docker-compose.yml` services | `ams.<service>` elements: title, image/build, published ports, `smr.monitor`/`smr.autoheal`, compose profile |
| `deploy/swarm-edge-nodes.yml` services | `edge.<service>` elements: `smr.category`/`smr.device`, placement, image |
| `stack_controller/stacks.yml` | `env_overrides` as metadata on the edge stack |
| `smr.description` label on each service (**new**) | The element's description |

Descriptions come from a new `smr.description` label, added next to the existing `smr.*` labels in both compose files. Adding a service means writing one label, and the service appears on the diagram with no `.c4` edits. That's the "easy to keep up to date" part. (`extend` can't set descriptions, so they have to live in the generated file or at its source.)

**Hand-written** in `.c4`: everything not in a deploy file. That includes the robot, PLC, NAS, Pis' host-side `imu_host`, downstream consumers and people. It also covers every relationship (protocol, port, topic), drill-down children (e.g. `fastapi-app` → capture gate, batch workers, LiveSampler, PLC watcher), links to code and docs, and the flows.

### 3.3 Model contents (first pass)

- **People:** operator (runs tests from the dashboard), student/researcher (queries via pgAdmin), lab admin.
- **Robot cell (192.168.1.x):** FANUC robot → `tcp` (CSV lines, TCP 5001); cell PLC L32E ← `fastapi-app` (`Db_Stop`, EtherNet/IP 44818) and ← IMU Pis (`Data_Start`).
- **Edge (Swarm workers):** `imu-106`…`imu-111` (container + host `imu_host` over `/run/imu-hw`), `camera-front`, `camera-side` → `mqtt-broker` (`imu/<id>`, `camera/<id>`, 1883). NTP from `ntp`.
- **AMS host `IIoT` (192.168.2.100):** `mqtt-broker`, `fastapi-app`, `tcp`, `stack-controller` (→ Docker socket → Swarm manager), `web` (nginx: SPA, docs, `/architecture/`, `/api/` proxy), `ntp`, `pgadmin`. Profile-only `postgres` is shown as "local-db profile".
- **NAS (192.168.1.104):** Postgres 5433 ← `fastapi-app`, `tcp`, `pgadmin`; NFS backups/logs ← `fastapi-app`, `tcp`.
- **Downstream:** image analysis machine, digital twin (`VITE_TWINS_URL`), AI service (`VITE_AI_URL`), student queries. These get **placeholder** descriptions until someone confirms what each is and who owns it.
- **Repos** as metadata + links on each element: this repo, `wku-smr-lab-imu-edge-node` (branch `plc_update`), `camera_sensor_fusion`.

Views: landscape · AMS host · edge · `fastapi-app` internals · deployment (hosts/IPs/Swarm placement) · flows: *IMU sample → DB*, *robot line → DB*, *Start Monitoring / Start Session (deploy via stack-controller)*, *PLC stop → drain → backup*, *live updates to the dashboard (`/ws/*`)*, *health & watchdog*.

### 3.4 Showing what's out of date

There are two different meanings. Both are covered, and they're kept separate:

1. **The diagram is missing something:** a service was added to or removed from a deploy file. `tests/architecture_test.py` regenerates the inventory in memory and fails if `generated/inventory.c4` differs, or if any service lacks `smr.description`. This is the same pattern as the existing `env_overrides` test. A hand-written relationship pointing at a removed service makes `likec4 validate` fail.
2. **The code changed since the diagram was last reviewed:** each hand-written element gets `metadata { repo '…'; paths '…'; reviewed '2026-10-27' }`. `sync.py --status` looks up the last commit touching those paths: `git log` for this repo, `gh api …/commits?path=` for the edge repos. Where it's newer than `reviewed`, it writes `#changed-since-review` into `generated/status.c4`. That tag is styled amber and listed in a "Needs review" view. Re-reviewing means bumping the date. `status.c4` isn't checked by the test, since it changes with every commit.

**Not in scope (possible phase 5):** *runtime* staleness, like "this Pi runs an older IMU image than `plc_update` HEAD" or live health colours on the canvas. That needs images labelled with their git SHA (`org.opencontainers.image.revision`) and a page that polls `/api/system/containers` and `/devices`. LikeC4's React components could render that inside the dashboard later, reusing this model.

### 3.5 Hosting

- **`web/dockerfile`:** builder `node:20-alpine` → `node:22-alpine`. Add `npm run arch:build` (`likec4 build --no-use-dot --base /architecture/ -o arch-dist architecture`) after `docs:build`, then copy `arch-dist` to `/usr/share/nginx/html/architecture`.
- **`web/nginx.conf`:** a `location /architecture/` like `/docs/`.
- **`web/package.json`:** devDependency `likec4` pinned to an exact version (it releases weekly), plus scripts `arch:dev` (`likec4 start architecture`), `arch:build`, `arch:check` (`likec4 validate architecture`).
- **Links:** docs nav + Overview sidebar ("Architecture (interactive)"), a link in `overview/structure.md`, and optionally a header link in the dashboard.
- **Docs embedding (phase 3):** load the `likec4-views.js` the build already produces and replace the three PNGs in `overview/structure.md` with `<likec4-view view-id="…">`. That needs one VitePress config line to treat `likec4-*` tags as custom elements.

## 4. Phases

| Phase | Delivers | Done when |
| --- | --- | --- |
| **1. Model + site** | `spec.c4`, hand-written landscape/AMS/edge model, static views, build into the web image at `/architecture/` | Site loads on prod; every element has a description and code link; `likec4 validate` clean |
| **2. Generated inventory + drift test** | `smr.description` labels in `docker-compose.yml`, `docker-compose.local.yml`, `swarm-edge-nodes.yml`; `architecture/sync.py`; `generated/inventory.c4`; `tests/architecture_test.py`; model refactored to `extend` generated elements | Adding a dummy service with a label makes it appear; without regenerating, the test fails |
| **3. Flows + docs** | Dynamic views for the six flows; web-component embeds replace the PNGs; new docs page "Keeping the architecture current" | `structure.md` has no static diagrams left |
| **4. Freshness** | `reviewed`/`paths`/`repo` metadata on hand-written elements; `sync.py --status`; amber styling + "Needs review" view | Touching `fast_server/plc_listener.py` after its `reviewed` date flags the PLC watcher |
| 5. (optional) Live overlay | Image revision labels, React embed in the dashboard with live health/version | Separate plan if wanted |

Phases 1 and 2 could be swapped (generator first, then hand-write around it). I'd do the model first, so you see the result early and the element ids settle before they're generated.

## 5. Keeping it current (the workflow)

- **Adding or removing a service:** set `smr.description`, run `python architecture/sync.py`, and commit the regenerated file. The test enforces it.
- **Changing how things talk** (new topic, port, endpoint between services): edit the relationship in `model/*.c4` and bump `reviewed` on the elements you checked.
- **Preview:** `npm run arch:dev` in `web/`, or the LikeC4 VS Code extension, which previews live as you type.
- **Before a release:** open the "Needs review" view.
- Add a line to `CLAUDE.md` ("Notes for changes") so agents do the same.

## 6. Risks

- **Node 22 bump** for the web builder. Low risk, but `npm run build`/`docs:build` must be re-checked in the image.
- **LikeC4 moves fast.** Pin an exact version; upgrades are deliberate.
- **An invalid model doesn't block the web image** (decided): the build logs the error and `/architecture/` shows it instead of the diagram, so a broken diagram is visible but never blocks a dashboard deploy.
- **The image grows by about 6 MB.**
- **There's no CI.** The drift test only runs when someone runs the test suite, as with every other test here.

## 7. Decisions for you

1. **Tool:** LikeC4 (recommended) vs. a custom JSON + React Flow canvas in the dashboard.
2. **Descriptions in `smr.description` labels** in the compose/stack files (recommended) vs. all descriptions in `.c4` (fewer compose edits, but new services show up undescribed).
3. **Where it lives:** `/architecture/` next to the docs (recommended) vs. a tab inside the dashboard.
4. **Invalid model fails the web image build:** yes (recommended) or warn only.
5. **Phase 5 live overlay:** skip for now (recommended) or plan it too.
6. **Downstream consumers** (image analysis machine, digital twin, AI service): who owns them, and should they be on the diagram beyond a placeholder?

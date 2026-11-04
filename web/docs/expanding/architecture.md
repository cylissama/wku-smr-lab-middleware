# Keeping the architecture current

The [architecture site](/architecture/){target="_self"} and the diagrams embedded in these docs (for example on [How is this structured?](/overview/structure)) are all drawn from one model in `web/architecture/`, written in [LikeC4](https://likec4.dev). When the system changes, change the model in the same commit. Part of the model is generated from the deploy files, and a test fails when it falls behind them.

## What's generated and what's hand-written

| Part | Where | Who writes it |
| --- | --- | --- |
| One element per AMS container (title, image, ports, description) | `web/architecture/generated/inventory.c4` | `architecture/sync.py`, from `docker-compose.yml` |
| One deployment host per edge Pi, with the IMU or camera node it runs | `web/architecture/generated/edge-hosts.c4` | `architecture/sync.py`, from `deploy/swarm-edge-nodes.yml` and `deploy/.env.example` |
| Element kinds, colours, tags | `web/architecture/spec.c4` | by hand |
| People, robot cell, PLC, NAS, downstream consumers | `web/architecture/model/landscape.c4` | by hand |
| What's inside each AMS container (e.g. `fastapi-app`'s capture gate, workers, PLC watcher), code and docs links | `web/architecture/model/ams.c4` | by hand, `extend`ing the generated elements |
| IMU and camera nodes (`imu_host`, `imu_edge`, `camera_edge`) | `web/architecture/model/edge.c4` | by hand |
| Connections between zones (protocol, port, topic) | `web/architecture/model/connections.c4` | by hand |
| Element views (landscape, AMS host, edge, …) and the "Needs details" list | `web/architecture/views/static.c4` | by hand |
| Flows (IMU sample → DB, Start Session, session stop, health, …) | `web/architecture/views/flows.c4` | by hand |
| Machines and networks | `web/architecture/views/deployment.c4` | by hand |

Never edit `generated/` by hand. Each generated file says so at the top.

## Adding, removing or renaming a container

1. Give the service an `smr.description` label: one or two sentences on what it does. On the AMS host it goes under `labels:` in `docker-compose.yml` **and** `docker-compose.local.yml`. On the edge it goes under `deploy.labels:` in `deploy/swarm-edge-nodes.yml`, next to `smr.category`.

   ```yaml
   labels:
     smr.monitor: "true"
     smr.description: "Robot TCP listener (Python asyncio). Splits the robot stream into CSV lines, …"
   ```

2. Regenerate, from the repository root:

   ```bash
   python architecture/sync.py
   ```

3. Add what the generator can't know to `model/`: the container's connections (`ams.fastapi-app -[http]-> ams.<new>` …), code links, and its parts if it has any. A new edge `smr.category` also needs a node kind in `model/edge.c4` and an entry in `EDGE_NODES` in `architecture/sync.py`.
4. Commit the deploy file, `web/architecture/generated/` and your `model/` changes together.

`tests/architecture_test.py` fails while `generated/` doesn't match the deploy files, or when a service in `docker-compose.local.yml` has no `smr.description`:

```bash
python -m unittest tests.architecture_test
```

## Changing how things talk

A new MQTT topic, port, endpoint or step in a flow doesn't touch any deploy file, so no test catches it. Edit the relationship in `model/*.c4`, and the flow in `views/flows.c4` if the change affects one. Each flow step is written as the code path it follows (for example `POST /stacks/edge/deploy {services, env: IMU_PLC_TRIGGER=true}`), so a renamed route or env variable is easy to find with grep.

## Checking and previewing

In `web/` (Node 22 or newer):

| Command | What it does |
| --- | --- |
| `npm run arch:dev` | Live preview of the site at `http://localhost:5173`, updated as you save |
| `npm run arch:check` | Validates the model: unknown elements, bad syntax, invalid views |
| `npm run arch:build` | Builds the static site into `arch-dist/` |

The LikeC4 extension for VS Code (search for "LikeC4" in the Extensions panel) gives the same preview inside the editor, with completion and go-to-definition.

The `web` image runs the check and build (`web/scripts/build-architecture.sh`). **An invalid model doesn't fail the image build**: the build log shows the error and `/architecture/` shows an error page instead of the diagrams, so a broken diagram never blocks a dashboard deploy. Run `npm run arch:check` before you push.

::: tip No Node on the machine?
Run the check in a container from `web/`:

```bash
docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp -v $PWD:/app -w /app node:22-alpine npx likec4 validate architecture
```
:::

## Embedding a view in these docs

Any docs page can show a view from the model:

```md
<ArchitectureView view="imuToDb" title="IMU sample to the database" />
```

`view` is the view's id in `views/*.c4`. Add `variant="diagram"` or `variant="sequence"` to show a flow differently from its default. The diagram is clickable and opens the full interactive viewer; the caption links to the view on the architecture site. Views follow the docs' light or dark theme.

The component loads `/architecture/likec4-views.js`, which only exists in the built `web` image, so under `npm run docs:dev` only the link shows.

## Placeholders and work in progress

Elements tagged `#placeholder` (details unknown, such as the camera host service) or `#wip` (being built, such as the digital twin and AI service) are drawn faded with a dashed border and listed in the [Needs details](/architecture/view/placeholders/){target="_self"} view. When you fill one in, update its description and remove the tag.

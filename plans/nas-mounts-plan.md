# NAS Mounts — Stop the NAS Being a Container-Start Dependency

> Phase F of `dashboard-decouple-plan.md`, deferred until everything else was done.
> Moves the two NFS shares out of Docker volumes and onto the host, so
> `fastapi-app` and `tcp` can always start, even while the NAS is down.
> Needs `sudo` on IIoT (`192.168.2.100`); you run the host steps.

---

## 1. Do we need this?

**What it fixes.** Docker mounts the `logs` and `nas_backups` volumes itself, when
it starts a container. If the NAS (`192.168.1.104`) doesn't answer, Docker refuses to
start the container. Verified 2026-10-09: it hung 185 s, then failed with `error while
mounting volume … connection timed out`. None of our code runs, so the retries,
`/health`, and logging from phases A–G can't help.

That happens whenever `fastapi-app` or `tcp` **starts while the NAS is unreachable**:

| Situation | Without this plan | With it |
|---|---|---|
| Power blip; IIoT boots faster than the NAS | fastapi-app and tcp stay down until someone runs compose | both start; dashboard shows Database / Log files / Backup folder down; everything reconnects when the NAS is up |
| fastapi-app crashes, or the watchdog restarts it, while the NAS is down | most likely stays down: the restart has to remount the volumes (to confirm in drill 3) | restarts normally |
| `docker compose up -d` (deploy) while the NAS is down | fails for fastapi-app and tcp | works |
| NAS goes down while everything is already running | fine: `soft` mount, retries already handled | fine, and errors come back faster (see §3) |

**What it doesn't change.** The database is on the same NAS, so a NAS outage still
means no sessions and no stored data. This plan only keeps the API, dashboard and
robot listener **running and explaining the outage** instead of not starting.

**Recommendation:** do it. It's about 30 minutes plus a drill, and it's the last gap
in "every container restarts itself". Without it, the restart policy and the watchdog
from phase D are likely to fail exactly when the NAS is the problem.

---

## 2. Current state (checked 2026-10-09)

- Host: Ubuntu 24.04.5, systemd 255. `nfs-common` is **not installed**. Docker
  mounts NFS through the kernel without it, but `/etc/fstab` NFS mounts need its
  `mount.nfs` helper.
- Docker volumes (compose project `wku-smr-lab-middleware`), both NFSv3:
  - `nas_backups` → `192.168.1.104:/volume1/docker/postgres/backups` → `fastapi-app:/db_backups`
  - `logs` → `192.168.1.104:/volume1/docker/postgres/logs` → `fastapi-app:/fast_server/logs`, `tcp:/tcp-server/logs`
- Mount options in use: `vers=3, soft, nolock, proto=tcp, timeo=600, retrans=2`.
  `timeo=600` is 60 s per try, so one write to a dead NAS can block for about
  3 minutes before failing.
- NAS NFS ports 111 and 2049 are reachable from IIoT. Root mount propagation is
  `shared`, so host mounts can reach containers.
- Leftover volumes from an older compose project name: `project_logs`,
  `project_nas_backups`, `project_app_logs_local`. No container uses them. Inspect,
  then delete them in §4 step 8.

---

## 3. Design

**Host side: systemd automount from `/etc/fstab`.**

```
# NAS shares for the AMS broker stack (wku-smr-lab-middleware). Automounted on first
# access; nofail/_netdev so a missing NAS never blocks boot or container start.
192.168.1.104:/volume1/docker/postgres/backups /mnt/nas/backups nfs vers=3,soft,nolock,proto=tcp,timeo=50,retrans=2,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=15 0 0
192.168.1.104:/volume1/docker/postgres/logs    /mnt/nas/logs    nfs vers=3,soft,nolock,proto=tcp,timeo=50,retrans=2,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=15 0 0
```

- `x-systemd.automount`: systemd puts an automount point at `/mnt/nas/*` at boot,
  which always succeeds. The real NFS mount happens on first access, and is retried
  on the next access if it failed.
- `nofail,_netdev`: boot never waits on the NAS.
- `x-systemd.mount-timeout=15`: an access while the NAS is down fails after 15 s
  instead of hanging.
- `timeo=50,retrans=2` (5 s × 3 tries): once mounted, an operation on a dead NAS
  fails in about 15 s instead of about 3 min. The app's backup check already
  tolerates a slow mount (its `PathProbe` times out at 5 s and won't overlap), and
  log writes are on their own thread.
- Same `vers=3, soft, nolock, proto=tcp` as today, so the NAS sees the same client
  behavior.
- Key property: with automount, `/mnt/nas/*` is **either the NAS or an error, never
  the host's own disk**. A plain `nofail` mount would leave an empty local directory
  when the NAS is down, and backups would land on the Mini PC without anyone
  noticing.

**Container side: bind mounts with `rslave` propagation** (`docker-compose.yml`
only; `docker-compose.local.yml` keeps its local volumes):

```yaml
  fastapi-app:
    volumes:
      - type: bind
        source: ${NAS_MOUNT_ROOT:-/mnt/nas}/backups
        target: /db_backups
        bind: { propagation: rslave }
      - type: bind
        source: ${NAS_MOUNT_ROOT:-/mnt/nas}/logs
        target: /fast_server/logs
        bind: { propagation: rslave }
  tcp:
    volumes:
      - type: bind
        source: ${NAS_MOUNT_ROOT:-/mnt/nas}/logs
        target: /tcp-server/logs
        bind: { propagation: rslave }
```

- `rslave`: a mount that appears on the host after the container started (the NAS
  came back) shows up inside the container too, with no restart needed.
- Remove the `nas_backups` and `logs` entries from the top-level `volumes:`. Update
  the comment on the `postgres` service (`--profile local-db`), which mentions them.
- `NAS_MOUNT_ROOT` goes in `.env.example` with a one-line comment. Other machines
  use `docker-compose.local.yml`, which doesn't need it.

**App side: no code changes needed.** Phases B/E already handle it:
- If `/mnt/nas/backups` errors, the **Backup folder** chip goes red, and backups fail
  with the reason.
- If `/mnt/nas/logs` errors, logging falls back to stdout and the **Log files** chip
  goes red.

`BACKUP_DIR`/`LOG_DIR` are unchanged.

---

## 4. Rollout (maintenance window, no session running)

Check `curl -s http://192.168.2.100:8000/session` shows no session first.

**Host (you, with sudo):**

1. `sudo apt-get install -y nfs-common`
2. `sudo mkdir -p /mnt/nas/backups /mnt/nas/logs`
3. `sudo cp /etc/fstab /etc/fstab.bak-$(date +%F)`, then append the two lines from
   §3 to `/etc/fstab`.
4. `sudo systemctl daemon-reload && sudo systemctl restart remote-fs.target`
5. Verify:
   ```bash
   systemctl status mnt-nas-backups.automount mnt-nas-logs.automount   # active (waiting)
   ls /mnt/nas/backups | tail -3        # triggers the mount; shows existing .dump files
   findmnt /mnt/nas/backups             # type nfs, options include timeo=50
   touch /mnt/nas/logs/.write-test && rm /mnt/nas/logs/.write-test
   ```

**Repo (me):**

6. Compose change from §3, plus updates to `.env.example`,
   `web/docs/docker/compose.md` (Volumes section), `web/docs/operations/troubleshooting.md`
   (drop "may not start at all"), `web/docs/docker/health-and-logs.md`, and CLAUDE.md.
   `docker compose config -q` before handing over.

**Deploy (you):**

7. `docker compose up -d fastapi-app tcp`. Only these two change; no rebuild needed.
   Then I check:
   - `/health` shows `logs` and `backups` ok.
   - A new log file appears in `/mnt/nas/logs`.
   - **Create Backup** on the dashboard writes a `.dump` to `/mnt/nas/backups`.

**Cleanup (after the drill passes):**

8. `docker volume inspect` the old volumes. Then `docker volume rm
   wku-smr-lab-middleware_logs wku-smr-lab-middleware_nas_backups project_logs
   project_nas_backups project_app_logs_local`. This removes only Docker's mount
   definitions; the files on the NAS aren't touched.

**Rollback:** `git revert` the compose change, then `docker compose up -d
fastapi-app tcp`. Compose recreates the NFS volumes from their definitions. The fstab
lines can stay; they're harmless unused.

---

## 5. Drill (same window)

Simulate the NAS being off without touching it. Dropping its traffic on IIoT also
drops the database, which matches a real NAS outage:

```bash
sudo iptables -I OUTPUT -d 192.168.1.104 -j DROP      # NAS "off"
# ... checks below ...
sudo iptables -D OUTPUT -d 192.168.1.104 -j DROP      # NAS "back"
```

| # | Do | Expect |
|---|---|---|
| 1 | Block; wait 30 s | Dashboard: Database, Log files, Backup folder red with reasons; containers stay `healthy` (alive, degraded) |
| 2 | `docker compose up -d --force-recreate fastapi-app tcp` while blocked | **Both start within seconds** (the bug this plan fixes); `docker logs AMS-fastapi` shows DB retries; dashboard loads |
| 3 | `docker restart AMS-fastapi` while blocked | Restarts normally. Also tells us whether the old volume setup would have stayed down in this case. |
| 4 | Unblock | Within about 30 s, all chips go green without restarting anything. New log lines land on the NAS, and a manual backup works. |
| 5 | Optional: `sudo reboot` with the block made persistent, or the NAS actually off | After boot, every AMS container is up and the dashboard explains the outage |

Make sure the `iptables` rule is removed at the end (`sudo iptables -S OUTPUT`).

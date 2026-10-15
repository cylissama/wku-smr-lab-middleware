"""Draws the UML / flow figures for plans/completed/listener-switch-plan.md.

Run from anywhere with matplotlib installed:
    python plans/completed/figures/make_diagrams.py
PNGs are written next to this script.
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle

OUT = Path(__file__).resolve().parent
DPI = 170

# Palette (dataviz reference palette, light mode)
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK2 = "#52514e"
MUTED = "#8a8984"
GRID = "#d6d5cf"
PANEL = "#f3f2ee"
BLUE = "#2a78d6"     # existing components / RECORD
ORANGE = "#eb6834"   # new or changed
AQUA = "#1baf7a"     # MONITOR / live view
VIOLET = "#4a3aa7"   # external systems (Swarm, robot, devices)
RED = "#e34948"      # problems / drops
GRAY = "#8a8984"     # IDLE

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 10,
    "text.color": INK,
})


def tint(hex_color, amount=0.86):
    """Mix a color with white; amount=1 is white."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = (round(c + (255 - c) * amount) for c in (r, g, b))
    return f"#{r:02x}{g:02x}{b:02x}"


def canvas(w, h, title, subtitle=None, y_down=False):
    fig = plt.figure(figsize=(w, h), facecolor=SURFACE)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0) if y_down else ax.set_ylim(0, h)
    ax.axis("off")
    ty = 0.45 if y_down else h - 0.45
    ax.text(0.35, ty, title, fontsize=16, fontweight="bold", va="center")
    if subtitle:
        sy = 0.82 if y_down else h - 0.82
        ax.text(0.35, sy, subtitle, fontsize=10.5, color=INK2, va="center")
    return fig, ax


def save(fig, name):
    fig.savefig(OUT / name, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)
    print("wrote", name)


def box(ax, x, y, w, h, text="", color=BLUE, fill=None, fs=10, bold=False,
        text_color=INK, lw=1.6, radius=0.08, ha="center", dashed=False, z=2):
    """Rounded box with (x, y) = lower-left (or upper-left on y-down axes)."""
    patch = FancyBboxPatch(
        (x, y), w, h, boxstyle=f"round,pad=0,rounding_size={radius}",
        fc=fill if fill is not None else tint(color), ec=color, lw=lw,
        ls="--" if dashed else "-", zorder=z,
    )
    ax.add_patch(patch)
    if text:
        tx = x + w / 2 if ha == "center" else x + 0.12
        ax.text(tx, y + h / 2, text, ha=ha, va="center", fontsize=fs,
                fontweight="bold" if bold else "normal", color=text_color,
                zorder=z + 1, linespacing=1.35)
    return patch


def arrow(ax, p1, p2, color=INK2, lw=1.4, dashed=False, rad=0.0, head="-|>",
          ms=13, z=3, shrink=0):
    a = FancyArrowPatch(
        p1, p2, arrowstyle=head, mutation_scale=ms, color=color, lw=lw,
        ls="--" if dashed else "-", connectionstyle=f"arc3,rad={rad}",
        shrinkA=shrink, shrinkB=shrink, zorder=z,
    )
    ax.add_patch(a)
    return a


def polyline_arrow(ax, pts, color=INK2, lw=1.4, dashed=False, z=3):
    xs, ys = zip(*pts[:-1])
    ax.plot(list(xs) + [pts[-1][0]], list(ys) + [pts[-1][1]], color=color,
            lw=lw, ls="--" if dashed else "-", zorder=z, solid_capstyle="round")
    arrow(ax, pts[-2], pts[-1], color=color, lw=lw, dashed=dashed, z=z)


def label(ax, x, y, text, fs=9, color=INK2, ha="center", va="center", bg=SURFACE,
          bold=False, z=5):
    ax.text(x, y, text, fontsize=fs, color=color, ha=ha, va=va, zorder=z,
            fontweight="bold" if bold else "normal", linespacing=1.3,
            bbox=dict(boxstyle="round,pad=0.18", fc=bg, ec="none") if bg else None)


def legend_row(ax, x, y, items, fs=9):
    for color, text in items:
        ax.add_patch(FancyBboxPatch((x, y - 0.09), 0.28, 0.18,
                                    boxstyle="round,pad=0,rounding_size=0.03",
                                    fc=tint(color), ec=color, lw=1.4, zorder=4))
        ax.text(x + 0.38, y, text, fontsize=fs, color=INK2, va="center", zorder=4)
        x += 0.38 + len(text) * 0.075 + 0.45


# ---------------------------------------------------------------------------
# 1. State machine
# ---------------------------------------------------------------------------
def state(ax, cx, cy, name, color, rows, w=3.5, h=1.95):
    x, y = cx - w / 2, cy - h / 2
    box(ax, x, y, w, h, color=color, fill=tint(color, 0.9), radius=0.22, lw=2)
    ax.text(cx, y + h - 0.3, name, ha="center", va="center", fontsize=12.5,
            fontweight="bold", color=INK, zorder=4)
    ax.plot([x + 0.12, x + w - 0.12], [y + h - 0.58] * 2, color=color, lw=1, zorder=4)
    for i, (k, v) in enumerate(rows):
        ty = y + h - 0.88 - i * 0.36
        ax.text(x + 0.2, ty, k, fontsize=9, color=INK2, va="center", zorder=4)
        ax.text(x + 0.95, ty, v, fontsize=9, color=INK, va="center", zorder=4)
    return x, y, w, h


def fig_state_machine():
    fig, ax = canvas(15, 9.6, "Capture-mode state machine",
                     "UML state diagram · owned by fastapi-app (fast_server/capture.py), pushed to tcp_server via PUT /capture")

    idle = (3.2, 4.4)
    mon = (7.5, 7.0)
    rec = (11.8, 4.4)
    stop = (7.5, 1.75)

    state(ax, *idle, "IDLE", GRAY, [("stack", "removed"), ("data", "dropped at handler"), ("DB", "no writes")])
    state(ax, *mon, "MONITOR", AQUA, [("stack", "selected services up"), ("data", "gate → live samples"), ("DB", "no writes")])
    state(ax, *rec, "RECORD", BLUE, [("stack", "selected services up"), ("data", "gate → samples + queue"), ("DB", "batched inserts")])
    state(ax, *stop, "STOPPING", ORANGE, [("stack", "being removed"), ("data", "dropped (gate closed)"), ("DB", "drain final batches")])

    # initial pseudo-state + choice
    ax.add_patch(Circle((0.55, 8.05), 0.16, color=INK, zorder=5))
    ax.add_patch(Polygon([(1.55, 8.35), (1.85, 8.05), (1.55, 7.75), (1.25, 8.05)],
                         closed=True, fc=SURFACE, ec=INK, lw=1.5, zorder=5))
    arrow(ax, (0.72, 8.05), (1.25, 8.05), color=INK)
    label(ax, 0.95, 8.4, "boot", fs=8.5)
    arrow(ax, (1.55, 7.75), (1.9, 5.38), color=INK)
    label(ax, 1.05, 6.6, "[no open\nsession]", fs=8.5, ha="center")
    polyline_arrow(ax, [(1.85, 8.05), (2.3, 8.05), (2.3, 8.3), (13.2, 8.3), (13.2, 5.38)], color=INK)
    label(ax, 7.5, 8.3, "[open session found] / restore RECORD with session.devices", fs=8.5)

    # IDLE <-> MONITOR
    arrow(ax, (3.6, 5.38), (5.75, 6.75), color=AQUA, lw=1.8, rad=-0.18)
    label(ax, 3.55, 6.45, "POST /listen/start {devices}\n/ deploy selected services", fs=8.5, ha="center")
    arrow(ax, (5.75, 6.25), (4.4, 5.38), color=GRAY, lw=1.8, rad=-0.1)
    label(ax, 6.55, 5.75, "POST /listen/stop\n/ remove stack", fs=8.5)

    # MONITOR -> RECORD
    arrow(ax, (9.25, 6.75), (11.4, 5.38), color=BLUE, lw=1.8, rad=-0.18)
    label(ax, 11.0, 6.55, "session/start {label, devices}\n/ create session; reuse deployment\n(redeploy --prune if selection changed)", fs=8.5)

    # IDLE -> RECORD and rollback
    arrow(ax, (4.95, 4.75), (10.05, 4.75), color=BLUE, lw=1.8)
    label(ax, 7.5, 4.98, "session/start {label, devices} / create session row → deploy", fs=8.5)
    arrow(ax, (10.05, 4.05), (4.95, 4.05), color=RED, lw=1.5, dashed=True)
    label(ax, 7.5, 3.82, "[deploy failed] / end session (rollback)", fs=8.5, color=RED)

    # RECORD -> STOPPING -> IDLE
    arrow(ax, (11.8, 3.42), (9.25, 1.95), color=ORANGE, lw=1.8, rad=-0.15)
    label(ax, 12.0, 2.3, "session/stop\n/ close gate first", fs=8.5)
    arrow(ax, (5.75, 1.95), (3.2, 3.42), color=GRAY, lw=1.8, rad=-0.15)
    label(ax, 2.9, 2.3, "[queues drained or 10 s timeout]\n/ end session, pg_dump backup", fs=8.5)

    legend_row(ax, 0.4, 0.35, [(GRAY, "idle"), (AQUA, "listen only"), (BLUE, "storing"),
                               (ORANGE, "transitional"), (RED, "failure path")])
    save(fig, "01-capture-state-machine.png")


# ---------------------------------------------------------------------------
# 2. Component diagram, before vs after
# ---------------------------------------------------------------------------
def component_panel(ax, ox, title, after):
    W, H = 10.0, 9.0
    ax.add_patch(Rectangle((ox, 0.9), W, H, fc=PANEL, ec="none", zorder=0))
    ax.text(ox + 0.25, 9.55, title, fontsize=13, fontweight="bold", va="center")

    new = ORANGE if after else BLUE
    # Dashboard
    box(ax, ox + 3.55, 8.0, 3.7, 0.95,
        "web dashboard\n+ DeviceSelector · mode badge · Monitor buttons" if after else "web dashboard\nstart/stop session · message feeds",
        color=new if after else BLUE, fs=9)
    # Edge nodes / robot
    box(ax, ox + 0.2, 4.95, 1.75, 1.45, "Edge nodes\n(Swarm)\nIMU ×5 · camera ×2", color=VIOLET, fs=9)
    box(ax, ox + 0.2, 1.65, 1.75, 1.0, "Robot arm\n(TCP stream)", color=VIOLET, fs=9)
    box(ax, ox + 2.25, 5.3, 1.1, 0.8, "Mosquitto\nMQTT", color=MUTED, fs=8.5)

    # fastapi-app
    fx, fy, fw, fh = ox + 3.55, 3.85, 3.7, 3.65
    box(ax, fx, fy, fw, fh, color=BLUE, fill=SURFACE, radius=0.12)
    ax.text(fx + 0.15, fy + fh - 0.25, "fastapi-app", fontsize=10, fontweight="bold", va="center")
    if after:
        inner = [("MQTT handlers  imu/# · camera/#", BLUE),
                 ("CaptureController\nmode · devices · LiveSampler", ORANGE),
                 ("imu / camera queues  (RECORD only)", ORANGE),
                 ("batch workers  (drop batch if no session)", ORANGE)]
    else:
        inner = [("MQTT handlers  imu/# · camera/#", BLUE),
                 ("parse → always enqueue", RED),
                 ("imu / camera queues", BLUE),
                 ("batch workers  (retry failed batch forever)", RED)]
    iy = fy + fh - 0.6
    for text, c in inner:
        hh = 0.62 if "\n" in text else 0.5
        iy -= hh
        box(ax, fx + 0.15, iy, fw - 0.3, hh, text, color=c, fs=8.5)
        iy -= 0.14

    # tcp_server
    tx, ty, tw, th = ox + 3.55, 1.25, 3.7, 2.15
    box(ax, tx, ty, tw, th, color=BLUE, fill=SURFACE, radius=0.12)
    ax.text(tx + 0.15, ty + th - 0.25, "tcp_server", fontsize=10, fontweight="bold", va="center")
    if after:
        tinner = [("line parser + capture gate", ORANGE), ("robot_queue → robot_worker", BLUE),
                  ("GET /queue/status · PUT /capture", ORANGE)]
    else:
        tinner = [("line parser → always enqueue", RED), ("robot_queue → robot_worker", BLUE),
                  ("GET /queue/status", BLUE)]
    iy = ty + th - 0.5
    for text, c in tinner:
        iy -= 0.42
        box(ax, tx + 0.15, iy, tw - 0.3, 0.42, text, color=c, fs=8.5)
        iy -= 0.1

    # stack-controller, Postgres
    box(ax, ox + 7.75, 5.35, 2.05, 1.35,
        "stack-controller\n+ GET /services\n+ filtered deploy --prune" if after else "stack-controller\ndeploy / remove\nwhole edge stack",
        color=new, fs=8.5)
    box(ax, ox + 7.75, 2.05, 2.05, 1.35,
        "Postgres (NAS)\n+ session.devices JSONB" if after else "Postgres (NAS)\nsession-scoped rows",
        color=new, fs=8.5)

    # arrows
    arrow(ax, (ox + 1.95, 5.7), (ox + 2.25, 5.7))
    label(ax, ox + 2.1, 6.3, "MQTT", fs=8)
    arrow(ax, (ox + 3.35, 5.7), (ox + 3.7, 6.75))
    arrow(ax, (ox + 1.95, 2.15), (ox + 3.7, 2.68))
    label(ax, ox + 2.75, 1.95, "TCP :5001", fs=8)
    arrow(ax, (ox + 7.25, 4.4), (ox + 7.75, 3.2))
    arrow(ax, (ox + 7.25, 1.9), (ox + 7.75, 2.4))
    label(ax, ox + 7.55, 3.75, "INSERT", fs=8)
    arrow(ax, (ox + 7.25, 6.0), (ox + 7.75, 6.0), head="<|-|>")
    arrow(ax, (ox + 5.4, 7.5), (ox + 5.4, 8.0), head="<|-|>")
    label(ax, ox + 6.35, 7.82, "REST + 4 WebSockets", fs=8)
    arrow(ax, (ox + 5.4, 3.4), (ox + 5.4, 3.85), head="<|-|>", color=ORANGE if after else INK2)
    polyline_arrow(ax, [(ox + 8.8, 6.7), (ox + 8.8, 7.6), (ox + 1.08, 7.6), (ox + 1.08, 6.4)])
    label(ax, ox + 2.3, 7.6, "docker stack deploy / rm", fs=8)

    if after:
        note = ("Data reaches the DB only in RECORD, only from selected devices.\n"
                "MONITOR shows throttled live samples with no writes.")
        c = ORANGE
    else:
        note = ("Every message is parsed and queued, session or not. With no session the insert\n"
                "fails, the batch is kept and retried — and lands in the NEXT session.")
        c = RED
    box(ax, ox + 0.2, 0.05, W - 0.4, 0.7, note, color=c, fs=8.8, fill=tint(c, 0.9))


def fig_components():
    fig, ax = canvas(21, 10.4, "System components — before and after")
    ax.set_ylim(-0.1, 10.3)
    ax.texts[0].set_position((0.35, 10.0))
    component_panel(ax, 0.3, "Today", after=False)
    component_panel(ax, 10.7, "Proposed", after=True)
    legend_row(ax, 13.6, 10.0, [(BLUE, "existing"), (ORANGE, "new / changed"), (RED, "problem"), (VIOLET, "external")])
    save(fig, "02-component-before-after.png")


# ---------------------------------------------------------------------------
# Sequence diagram engine (y grows downward)
# ---------------------------------------------------------------------------
def sequence(fname, title, subtitle, parts, steps, col=3.0, row=0.62, left=1.0):
    xs = {k: left + col * i + col / 2 for i, (k, _, _) in enumerate(parts)}
    width = left + col * len(parts) + 0.4

    # dry run for height
    y = 2.0
    for s in steps:
        y += step_height(s, row)
    height = y + 0.6

    fig, ax = canvas(width, height, title, subtitle, y_down=True)
    head_y = 1.25
    for key, name, color in parts:
        x = xs[key]
        box(ax, x - col / 2 + 0.2, head_y, col - 0.4, 0.62, name, color=color, fs=9.5, bold=True)
        ax.plot([x, x], [head_y + 0.62, height - 0.3], color=GRID, lw=1.3, ls=(0, (5, 4)), zorder=1)

    y = 2.0
    frames = []
    for s in steps:
        kind = s[0]
        h = step_height(s, row)
        if kind in ("msg", "ret"):
            _, a, b, text = s[:4]
            color = s[4] if len(s) > 4 else (INK if kind == "msg" else INK2)
            ly = y + h - 0.2
            arrow(ax, (xs[a], ly), (xs[b], ly), color=color, lw=1.4, dashed=(kind == "ret"),
                  head="-|>" if kind == "msg" else "->")
            label(ax, (xs[a] + xs[b]) / 2, ly - 0.24 - 0.13 * text.count("\n"), text, fs=8.5,
                  color=INK if kind == "msg" else INK2, bg=None)
        elif kind == "self":
            _, a, text = s[:3]
            color = s[3] if len(s) > 3 else INK
            x = xs[a]
            top, bot = y + 0.18, y + h - 0.12
            ax.plot([x, x + 0.35, x + 0.35], [top, top, bot], color=color, lw=1.4, zorder=3)
            arrow(ax, (x + 0.35, bot), (x + 0.02, bot), color=color, lw=1.4)
            label(ax, x + 0.5, (top + bot) / 2, text, fs=8.5, ha="left", color=color, bg=SURFACE)
        elif kind == "note":
            _, a, b, text, color = s
            x0 = min(xs[a], xs[b]) - col / 2 + 0.3
            x1 = max(xs[a], xs[b]) + col / 2 - 0.3
            box(ax, x0, y + 0.1, x1 - x0, h - 0.2, text, color=color, fs=8.6, fill=tint(color, 0.9), z=6)
        elif kind == "frame":
            frames.append((s[1], s[2], s[3], y))
        elif kind == "else":
            fx0, fx1 = frames[-1][1], frames[-1][2]
            x0 = xs[fx0] - col / 2 + 0.1
            x1 = xs[fx1] + col / 2 - 0.1
            ax.plot([x0, x1], [y + 0.1, y + 0.1], color=MUTED, lw=1.1, ls=(0, (4, 3)), zorder=2)
            label(ax, x0 + 0.12, y + 0.3, s[1], fs=8.5, ha="left", color=INK2, bg=None)
        elif kind == "end":
            name, a, b, y0 = frames.pop()
            x0 = xs[a] - col / 2 + 0.1
            x1 = xs[b] + col / 2 - 0.1
            ax.add_patch(Rectangle((x0, y0 + 0.05), x1 - x0, y - y0, fc="none", ec=MUTED, lw=1.2, zorder=2))
            tw = 0.11 * len(name) + 0.3
            ax.add_patch(Polygon([(x0, y0 + 0.05), (x0 + tw, y0 + 0.05), (x0 + tw, y0 + 0.28),
                                  (x0 + tw - 0.12, y0 + 0.4), (x0, y0 + 0.4)],
                                 closed=True, fc=PANEL, ec=MUTED, lw=1.2, zorder=3))
            ax.text(x0 + 0.1, y0 + 0.23, name, fontsize=8.5, fontweight="bold", va="center", zorder=4)
        y += h
    save(fig, fname)


def step_height(s, row):
    kind = s[0]
    if kind in ("msg", "ret"):
        return row + 0.2 * s[3].count("\n")
    if kind == "self":
        return row + 0.12 + 0.2 * s[2].count("\n")
    if kind == "note":
        return 0.62 + 0.2 * s[3].count("\n")
    if kind == "frame":
        return 0.5
    if kind == "else":
        return 0.45
    if kind == "end":
        return 0.25
    return row


def fig_seq_start():
    parts = [("D", "Dashboard", BLUE), ("F", "fastapi-app", BLUE), ("P", "Postgres", BLUE),
             ("T", "tcp_server", BLUE), ("S", "stack-controller", ORANGE), ("E", "Edge nodes (Swarm)", VIOLET)]
    steps = [
        ("note", "D", "D", "operator ticks\nimu-106, imu-107, robot", AQUA),
        ("msg", "D", "F", "GET /session/start/{label}\n?devices=imu-106&devices=imu-107&devices=robot"),
        ("msg", "F", "P", "INSERT session (label, devices JSONB)"),
        ("ret", "P", "F", "session_id"),
        ("self", "F", "mode = RECORD\ndevices = {imu-106, imu-107, robot}", ORANGE),
        ("msg", "F", "T", "PUT /capture {mode: RECORD, robot_enabled: true}", ORANGE),
        ("ret", "T", "F", "200"),
        ("msg", "F", "S", "POST /stacks/edge/deploy {services: [imu-106, imu-107]}", ORANGE),
        ("self", "S", "write filtered compose\n(selected services only)", ORANGE),
        ("msg", "S", "E", "docker stack deploy --prune"),
        ("frame", "alt", "D", "E"),
        ("ret", "S", "F", "success"),
        ("ret", "F", "D", "{success: true, id}"),
        ("note", "E", "F", "imu/106, imu/107 publish → gate accepts → imu_queue → batch INSERT", BLUE),
        ("else", "[deploy failed]"),
        ("ret", "S", "F", "error", RED),
        ("msg", "F", "P", "UPDATE session SET ended_at (rollback)", RED),
        ("self", "F", "mode = IDLE", RED),
        ("msg", "F", "T", "PUT /capture {mode: IDLE}", RED),
        ("ret", "F", "D", "{success: false, error}", RED),
        ("end",),
    ]
    sequence("03-seq-start-session.png", "Start a recording session with a device selection",
             "UML sequence diagram · session row first, then gate opens, then only the selected services are deployed",
             parts, steps, col=3.25)


def fig_seq_stop():
    parts = [("D", "Dashboard", BLUE), ("F", "fastapi-app", BLUE), ("T", "tcp_server", BLUE),
             ("S", "stack-controller", ORANGE), ("E", "Edge nodes (Swarm)", VIOLET), ("P", "Postgres / NAS", BLUE)]
    steps = [
        ("msg", "D", "F", "GET /session/stop"),
        ("self", "F", "mode = STOPPING\ngate closed: new messages dropped", ORANGE),
        ("msg", "F", "T", "PUT /capture {mode: STOPPING}", ORANGE),
        ("msg", "F", "S", "POST /stacks/edge/remove"),
        ("msg", "S", "E", "docker stack rm edge"),
        ("ret", "S", "F", "success"),
        ("frame", "loop  [until drained or 10 s]", "F", "P"),
        ("self", "F", "imu/camera: qsize + pending"),
        ("msg", "F", "T", "GET /queue/status"),
        ("ret", "T", "F", "{depth, pending, empty}"),
        ("note", "F", "P", "workers flush their last batches → INSERT", BLUE),
        ("end",),
        ("msg", "F", "P", "UPDATE session SET ended_at"),
        ("msg", "F", "P", "pg_dump → /db_backups"),
        ("self", "F", "mode = IDLE", GRAY),
        ("msg", "F", "T", "PUT /capture {mode: IDLE}", ORANGE),
        ("ret", "F", "D", "{success, backup, still_buffered?}"),
    ]
    sequence("04-seq-stop-session.png", "Stop a recording session",
             "UML sequence diagram · the gate closes before anything else, so nothing arrives after the drain starts",
             parts, steps, col=3.1)


def fig_seq_monitor():
    parts = [("D", "Dashboard", BLUE), ("F", "fastapi-app", BLUE), ("T", "tcp_server", BLUE),
             ("S", "stack-controller", ORANGE), ("E", "Edge nodes (MQTT)", VIOLET), ("R", "Robot arm", VIOLET),
             ("P", "Postgres", BLUE)]
    steps = [
        ("msg", "D", "F", "POST /listen/start {devices: [camera-front, robot]}", AQUA),
        ("self", "F", "mode = MONITOR", AQUA),
        ("msg", "F", "T", "PUT /capture {MONITOR, robot_enabled: true}", AQUA),
        ("msg", "F", "S", "POST /stacks/edge/deploy {services: [camera-front]}"),
        ("msg", "S", "E", "docker stack deploy --prune"),
        ("ret", "F", "D", "{mode: MONITOR}"),
        ("frame", "loop  [while monitoring]", "D", "P"),
        ("msg", "E", "F", "MQTT camera/front  payload"),
        ("self", "F", "parse → gate → LiveSampler"),
        ("ret", "F", "D", "/ws/camera  live sample (≤ 1/s per device)", AQUA),
        ("msg", "R", "T", "CSV line"),
        ("ret", "T", "F", "POST /send/robot  summary (≤ 1/s)", AQUA),
        ("ret", "F", "D", "/ws/robot  live sample", AQUA),
        ("note", "P", "P", "no writes —\nqueues never filled", GRAY),
        ("end",),
        ("msg", "D", "F", "POST /listen/stop"),
        ("msg", "F", "S", "POST /stacks/edge/remove"),
        ("self", "F", "mode = IDLE", GRAY),
        ("msg", "F", "T", "PUT /capture {IDLE}"),
    ]
    sequence("05-seq-monitor-mode.png", "Monitor (listen-only) mode",
             "UML sequence diagram · devices run and the dashboard shows live data, but nothing is stored",
             parts, steps, col=2.85)


# ---------------------------------------------------------------------------
# 6. Activity diagram (y grows downward)
# ---------------------------------------------------------------------------
def action(ax, cx, cy, text, color=BLUE, w=3.6, h=0.62):
    box(ax, cx - w / 2, cy - h / 2, w, h, text, color=color, radius=0.25, fs=9.2)


def decision(ax, cx, cy, text, w=3.9, h=1.05):
    ax.add_patch(Polygon([(cx, cy - h / 2), (cx + w / 2, cy), (cx, cy + h / 2), (cx - w / 2, cy)],
                         closed=True, fc=SURFACE, ec=INK, lw=1.5, zorder=2))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=9, zorder=3, linespacing=1.25)


def final(ax, cx, cy):
    ax.add_patch(Circle((cx, cy), 0.2, fc=SURFACE, ec=INK, lw=1.5, zorder=3))
    ax.add_patch(Circle((cx, cy), 0.12, color=INK, zorder=4))


def fig_activity():
    W, H = 12.5, 17.0
    fig, ax = canvas(W, H, "Ingest gate — per message", "UML activity diagram · same logic for MQTT handlers (fastapi-app) and TCP lines (tcp_server)", y_down=True)
    cx, rx = 4.6, 9.6

    ax.add_patch(Circle((cx, 1.6), 0.18, color=INK, zorder=4))
    action(ax, cx, 2.45, "MQTT message / TCP line arrives", VIOLET)
    decision(ax, cx, 3.85, "mode ∈ {MONITOR, RECORD}?")
    action(ax, rx, 3.85, "drop  (IDLE / STOPPING)", RED, w=3.2)
    action(ax, cx, 5.25, "parse payload  (parsing.py / tcp parser)")
    decision(ax, cx, 6.65, "parsed OK?")
    action(ax, rx, 6.65, "log + broadcast parse error", RED, w=3.2)
    decision(ax, cx, 8.15, "device in selection?")
    action(ax, rx, 8.15, "drop  (unselected device)", RED, w=3.2)
    decision(ax, cx, 9.65, "≥ 1 s since last sample\nfor this device?")
    action(ax, rx, 9.65, "broadcast live sample\non /ws/{category}", AQUA, w=3.2)
    ax.add_patch(Polygon([(cx, 10.75), (cx + 0.25, 11.0), (cx, 11.25), (cx - 0.25, 11.0)],
                         closed=True, fc=SURFACE, ec=INK, lw=1.5, zorder=3))
    decision(ax, cx, 12.2, "mode == RECORD?")
    action(ax, 1.35, 13.4, "done\n(not stored)", GRAY, w=1.9, h=0.75)
    action(ax, cx, 13.4, "queue.put(item) → worker batch", BLUE)
    decision(ax, cx, 14.65, "session still open\nat INSERT time?")
    action(ax, rx, 14.65, "log + DROP batch\n(never retried into next session)", ORANGE, w=3.6, h=0.75)
    action(ax, cx, 15.95, "batch INSERT → rows committed", BLUE)

    # main spine
    for a, b in [(1.78, 2.14), (2.76, 3.32), (4.37, 4.94), (5.56, 6.12), (7.18, 7.62), (8.68, 9.12), (10.18, 10.75), (11.25, 11.67)]:
        arrow(ax, (cx, a), (cx, b), color=INK)
    label(ax, cx + 0.3, 4.65, "yes", fs=8.5, ha="left")
    label(ax, cx + 0.3, 7.4, "yes", fs=8.5, ha="left")
    label(ax, cx + 0.3, 10.45, "no", fs=8.5, ha="left")
    # right branches
    for y, t in [(3.85, "no"), (6.65, "no"), (8.15, "no"), (9.65, "yes")]:
        arrow(ax, (cx + 1.95, y), (rx - 1.6, y), color=INK)
        label(ax, cx + 2.45, y - 0.22, t, fs=8.5, bg=None)
    # sample branch back to merge
    polyline_arrow(ax, [(rx, 9.96), (rx, 11.0), (cx + 0.25, 11.0)], color=INK)
    # end nodes for drops
    for y in (3.85, 6.65, 8.15):
        arrow(ax, (rx + 1.6, y), (rx + 2.15, y), color=INK)
        final(ax, rx + 2.35, y)
    # RECORD?
    polyline_arrow(ax, [(cx - 1.95, 12.2), (1.35, 12.2), (1.35, 13.02)], color=INK)
    label(ax, 2.2, 11.98, "no  (MONITOR)", fs=8.5, bg=None)
    arrow(ax, (cx, 12.73), (cx, 13.09), color=INK)
    label(ax, cx + 0.3, 12.9, "yes", fs=8.5, ha="left")
    arrow(ax, (1.35, 13.78), (1.35, 15.75), color=INK)
    final(ax, 1.35, 15.95)
    arrow(ax, (cx, 13.71), (cx, 14.12), color=INK)
    arrow(ax, (cx + 1.95, 14.65), (rx - 1.8, 14.65), color=INK)
    label(ax, cx + 2.45, 14.43, "no", fs=8.5, bg=None)
    arrow(ax, (rx + 1.8, 14.65), (rx + 2.15, 14.65), color=INK)
    final(ax, rx + 2.35, 14.65)
    arrow(ax, (cx, 15.18), (cx, 15.64), color=INK)
    label(ax, cx + 0.3, 15.4, "yes", fs=8.5, ha="left")
    arrow(ax, (cx + 1.8, 15.95), (cx + 2.15, 15.95), color=INK)
    final(ax, cx + 2.35, 15.95)

    legend_row(ax, 0.4, 16.65, [(AQUA, "live view"), (BLUE, "storage"), (RED, "dropped"), (ORANGE, "bug fix")])
    save(fig, "06-ingest-gate-activity.png")


# ---------------------------------------------------------------------------
# 7. Class diagram (y up)
# ---------------------------------------------------------------------------
def uml_class(ax, x, y, w, name, attrs, methods, color=BLUE, stereo=None):
    """(x, y) = top-left. Returns (x, y_top, w, h)."""
    lh = 0.3
    head = 0.55 + (0.25 if stereo else 0)
    h = head + lh * max(len(attrs), 1) + 0.15 + lh * max(len(methods), 0) + (0.15 if methods else 0)
    box(ax, x, y - h, w, h, color=color, fill=SURFACE, radius=0.05, lw=1.6)
    ax.add_patch(Rectangle((x, y - head), w, head, fc=tint(color, 0.85), ec=color, lw=1.6, zorder=2))
    if stereo:
        ax.text(x + w / 2, y - 0.25, f"«{stereo}»", ha="center", va="center", fontsize=8.5, color=INK2, zorder=4)
    ax.text(x + w / 2, y - head + 0.27, name, ha="center", va="center", fontsize=10.5, fontweight="bold", zorder=4)
    cy = y - head - 0.22
    for a in attrs:
        ax.text(x + 0.12, cy, a, fontsize=8.6, va="center", family="DejaVu Sans Mono", zorder=4)
        cy -= lh
    if methods:
        sep = cy + lh / 2 - 0.05
        ax.plot([x, x + w], [sep, sep], color=color, lw=1.2, zorder=4)
        cy -= 0.12
        for m in methods:
            ax.text(x + 0.12, cy, m, fontsize=8.6, va="center", family="DejaVu Sans Mono", zorder=4)
            cy -= lh
    return x, y, w, h


def fig_class():
    fig, ax = canvas(18.2, 11.2, "Class diagram — capture & device selection",
                     "UML class diagram · orange = new (fast_server/capture.py, devices), blue = existing code it calls")

    uml_class(ax, 0.4, 9.9, 2.6, "CaptureMode", ["IDLE", "MONITOR", "RECORD", "STOPPING"], [], ORANGE, "enum")
    uml_class(ax, 3.9, 9.9, 4.6, "CaptureState",
              ["mode: CaptureMode", "devices: set[str]", "session_id: int | None"],
              ["accepts(category, label) -> bool", "should_store() -> bool"], ORANGE, "dataclass")
    _, _, _, ch = uml_class(ax, 9.6, 9.9, 6.9, "CaptureController",
                            ["state: CaptureState", "sampler: LiveSampler", "_lock: asyncio.Lock"],
                            ["start_monitor(devices)", "stop_monitor()", "start_record(session_id, devices)",
                             "begin_stop() / finish_stop()", "restore_from_db(db)", "push_to_tcp()"], ORANGE)
    ctrl_bottom = 9.9 - ch
    _, _, _, dh = uml_class(ax, 0.4, 5.9, 2.9, "Device", ["key: str", "category: str", "device_label: str",
                                                          "service: str | None", "state: str"], [], ORANGE, "dataclass")
    _, _, _, sh = uml_class(ax, 3.9, 5.9, 4.6, "LiveSampler",
                            ["interval_s: float = 1.0", "_last: dict[str, float]", "_count: dict[str, int]"],
                            ["maybe_broadcast(category, label, data)"], ORANGE)
    _, _, _, cmh = uml_class(ax, 3.9, 3.3, 4.6, "ConnectionManager", ["active: list[WebSocket]"],
                             ["broadcast_json(payload)"], BLUE)
    _, _, _, kh = uml_class(ax, 0.4, 2.6, 3.0, "DeviceCatalog", ["robot: Device"],
                            ["list_devices()"], ORANGE)
    db_top = ctrl_bottom - 0.75
    _, _, _, dbh = uml_class(ax, 9.6, db_top, 6.9, "DatabaseSingleton",
                             ["current_session_id", "devices: dict"],
                             ["create_session(label, …, devices)   + devices arg", "get_latest_session()",
                              "get_session_devices(id)   new", "end_session()"], BLUE)
    cl_top = db_top - dbh - 0.35
    uml_class(ax, 9.6, cl_top, 6.9, "stack-controller client",
              ["(fast_server/main.py)"],
              ["call_stack_controller(action, stack, services)", "get_stack_services(stack)   new"],
              BLUE, "module functions")

    def diamond_at(x, y, ux, uy):
        """Filled composition diamond at (x, y) pointing along unit vector (ux, uy)."""
        L, Wd = 0.42, 0.13
        px, py = -uy * Wd, ux * Wd
        ax.add_patch(Polygon([(x, y), (x + ux * L / 2 + px, y + uy * L / 2 + py), (x + ux * L, y + uy * L),
                              (x + ux * L / 2 - px, y + uy * L / 2 - py)], closed=True, color=INK, zorder=6))

    def comp(whole, part):
        x, y = whole
        dx, dy = part[0] - x, part[1] - y
        n = (dx ** 2 + dy ** 2) ** 0.5
        ux, uy = dx / n, dy / n
        ax.plot([x + ux * 0.42, part[0]], [y + uy * 0.42, part[1]], color=INK, lw=1.3, zorder=5)
        diamond_at(x, y, ux, uy)

    def uses(p1, p2):
        arrow(ax, p1, p2, color=INK2, dashed=True, head="->", lw=1.3)

    # CaptureState -> CaptureMode
    arrow(ax, (3.9, 9.3), (3.0, 9.3), color=INK, head="->", lw=1.3)
    # Controller composes State and Sampler
    comp((9.6, 9.0), (8.5, 9.0))
    comp((9.6, ctrl_bottom + 0.35), (8.5, 5.9 - sh / 2))
    # Sampler uses ConnectionManager
    uses((6.2, 5.9 - sh), (6.2, 3.3))
    label(ax, 6.35, (5.9 - sh + 3.3) / 2, "broadcast live samples", fs=8.3, ha="left")
    # Controller uses DatabaseSingleton
    uses((13.05, ctrl_bottom), (13.05, db_top))
    label(ax, 13.2, (ctrl_bottom + db_top) / 2, "create / restore session", fs=8.3, ha="left")
    # Controller uses stack-controller client (routed down the right side)
    yc = cl_top - 0.9
    ax.plot([16.5, 17.1, 17.1], [8.2, 8.2, yc], color=INK2, lw=1.3, ls="--", zorder=3)
    uses((17.1, yc), (16.5, yc))
    ax.text(17.3, (8.2 + yc) / 2, "deploy / remove selected services", rotation=90, ha="center", va="center",
            fontsize=8.3, color=INK2)
    # Catalog has Devices; catalog uses client
    comp((1.85, 2.6), (1.85, 5.9 - dh))
    label(ax, 2.0, 5.9 - dh - 0.2, "0..*", fs=8.3, ha="left", bg=None)
    yk = 2.6 - kh + 0.3
    uses((3.4, yk), (9.6, yk))
    label(ax, 8.9, yk + 0.2, "list services", fs=8.3)
    save(fig, "07-class-diagram.png")


# ---------------------------------------------------------------------------
# 8. Wireframe (y down)
# ---------------------------------------------------------------------------
def checkbox(ax, x, y, state, s=0.26):
    ax.add_patch(FancyBboxPatch((x, y - s / 2), s, s, boxstyle="round,pad=0,rounding_size=0.04",
                                fc=BLUE if state else SURFACE, ec=BLUE if state else MUTED, lw=1.4, zorder=4))
    if state == "x":
        ax.plot([x + 0.06, x + 0.11, x + 0.21], [y, y + 0.07, y - 0.08], color="white", lw=1.8, zorder=5)
    elif state == "-":
        ax.plot([x + 0.06, x + 0.2], [y, y], color="white", lw=2.2, zorder=5)


def dot(ax, x, y, color):
    ax.add_patch(Circle((x, y), 0.07, color=color, zorder=5))


def fig_wireframe():
    W, H = 15, 9.6
    fig, ax = canvas(W, H, "Dashboard wireframe — device selection & capture mode",
                     "web/src/components/DeviceSelector.jsx inside DataDashboard.jsx (not final styling)", y_down=True)
    # header card
    box(ax, 0.4, 1.3, W - 0.8, 1.55, color=GRID, fill="white", radius=0.12, lw=1.2)
    ax.text(0.7, 1.72, "Data Dashboard", fontsize=13, fontweight="bold", va="center")
    box(ax, 0.7, 2.12, 2.9, 0.42, "●  Monitoring — not saved", color=AQUA, fs=9.2, radius=0.2)
    box(ax, 3.8, 2.12, 2.4, 0.42, "Most Recent Session: 412", color=GRID, fill=PANEL, fs=8.8, radius=0.06)
    bx = 6.9
    for text, c, w in [("Robot and IMU ▾", MUTED, 1.9), ("Stop Monitoring", AQUA, 1.75),
                       ("Start Session", BLUE, 1.6), ("Stop Session", MUTED, 1.5)]:
        box(ax, bx, 1.55, w, 0.48, text, color=c, fs=9, radius=0.06,
            fill="white" if c == MUTED else tint(c, 0.8))
        bx += w + 0.15
    ax.text(W - 0.65, 2.33, "monitoring: selection locked until you stop", fontsize=8.5, color=INK2, ha="right", va="center")

    # device card
    box(ax, 0.4, 3.15, W - 0.8, 5.0, color=GRID, fill="white", radius=0.12, lw=1.2)
    ax.text(0.7, 3.55, "Devices", fontsize=12, fontweight="bold", va="center")
    checkbox(ax, 2.2, 3.55, "-")
    ax.text(2.6, 3.55, "All devices  (4 of 8 selected)", fontsize=9.5, va="center")

    groups = [
        ("IMU", "-", [("imu-106", "x", AQUA, "running"), ("imu-107", "x", AQUA, "running"),
                      ("imu-108", None, MUTED, "not deployed"), ("imu-109", None, MUTED, "not deployed"),
                      ("imu-110", None, MUTED, "not deployed")]),
        ("Camera", "-", [("camera-front", "x", AQUA, "running"), ("camera-side", None, MUTED, "not deployed")]),
        ("Robot", "x", [("robot (TCP main)", "x", AQUA, "streaming")]),
    ]
    gx = 0.7
    for name, gstate, items in groups:
        box(ax, gx, 4.0, 4.4, 3.4, color=GRID, fill=PANEL, radius=0.08, lw=1)
        checkbox(ax, gx + 0.2, 4.35, gstate)
        ax.text(gx + 0.6, 4.35, name, fontsize=10.5, fontweight="bold", va="center")
        ax.text(gx + 4.2, 4.35, f"{sum(1 for i in items if i[1])}/{len(items)}", fontsize=9, color=INK2,
                va="center", ha="right")
        for i, (dev, st, c, status) in enumerate(items):
            yy = 4.9 + i * 0.5
            checkbox(ax, gx + 0.45, yy, st)
            ax.text(gx + 0.85, yy, dev, fontsize=9.3, va="center")
            dot(ax, gx + 2.75, yy, c)
            ax.text(gx + 2.9, yy, status, fontsize=8.5, color=INK2, va="center")
        gx += 4.65

    ax.text(0.7, 7.75, "Tri-state group boxes: ■ all, ▬ some, □ none.  Status dots come from GET /devices "
            "(stack-controller service state; robot from tcp_server).", fontsize=8.8, color=INK2, va="center")

    # message panels hint
    for i, ch in enumerate(["Camera Messages", "IMU Messages", "Robot Messages"]):
        x = 0.4 + i * 4.8
        box(ax, x, 8.4, 4.6, 0.95, color=GRID, fill="white", radius=0.1, lw=1.2)
        ax.text(x + 0.2, 8.65, ch, fontsize=9.5, fontweight="bold", va="center")
        ax.text(x + 0.2, 9.05, "[live] 31 msg/s · last sample …", fontsize=8.5, color=AQUA, va="center",
                family="DejaVu Sans Mono")
    save(fig, "08-device-selector-wireframe.png")


if __name__ == "__main__":
    fig_state_machine()
    fig_components()
    fig_seq_start()
    fig_seq_stop()
    fig_seq_monitor()
    fig_activity()
    fig_class()
    fig_wireframe()

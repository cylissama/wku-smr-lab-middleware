# Portainer

[Portainer](https://www.portainer.io) gives a web UI over Docker. It's linked from the dashboard's **Portainer** button when `VITE_PORTAINER_URL` is set at build time ([The dashboard](/overview/dashboard)).

It isn't part of either stack in this repo. Its old Swarm stack file is kept in `deploy/depr/portainer-agent-stack.yml` for reference.

::: warning Use it to look, not to deploy
The edge stack is deployed and removed by [stack-controller](/docker/stack-controller) every time someone starts or stops monitoring or a session. Scaling or redeploying `edge_*` services from Portainer will be undone by the next deploy, and can leave the dashboard's device states wrong in the meantime. For container health and logs on the AMS host, the dashboard's [Container Health and Logs](/docker/health-and-logs) boxes cover the same ground.
:::

::: info Placeholder
TODO: where Portainer runs now (the [hardware page](/hardware/) lists the Alienware PC, 192.168.1.119), its URL and port, and which environments (AMS host, edge Swarm) it's connected to. Or remove this page if it's no longer used.
:::

Login is `admin` plus the instance's current password. Get it from a lab lead or the team's password manager; this page is public, so it doesn't go here.

::: warning
An earlier version of this page had the Portainer password written in plaintext. It's already in this repo's git history; if that password is still in use, rotate it in Portainer's user settings.
:::

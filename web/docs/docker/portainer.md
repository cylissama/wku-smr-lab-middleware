# Portainer

[Portainer](https://www.portainer.io) runs on the Alienware machine in the Sandbox Lab, giving a web UI over the Swarm stack — useful for scaling IMU services (see [On-demand IMU activation](/docker/swarm#on-demand-imu-activation)) without SSHing into the manager for every command.

Login is `admin` plus the instance's current password — check with a lab lead or the team's shared password manager rather than a hardcoded value here, since this page is public and the password shouldn't be.

::: warning
An earlier version of this page had the Portainer password written in plaintext. It's already in this repo's git history — if that password is still in use, rotate it in Portainer's user settings.
:::

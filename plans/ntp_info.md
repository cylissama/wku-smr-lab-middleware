I have ran the following commands to disable and mask the systems chrony so that we use the containers time.

sudo systemctl stop chrony
sudo systemctl disable chrony
sudo systemctl mask chrony

sudo systemctl stop systemd-timesyncd
sudo systemctl disable systemd-timesyncd
sudo systemctl mask systemd-timesyncd

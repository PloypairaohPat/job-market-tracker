#!/bin/bash
# One-time setup of a fresh Ubuntu 24.04 server for the production stack
# (docs/deploy.md, "Bootstrap the server"). Run it once, as root:
#
#   bash bootstrap.sh "<your SSH public key>" [repo-url]
#
# The key is the single line from your laptop's id_ed25519.pub
# ("ssh-ed25519 AAAA... you@laptop"). It's written only to the deploy
# user's authorized_keys on this server, never to the repo.
#
# What it does (running it again repeats or skips each step harmlessly):
#   1. installs git, make, ufw, unattended-upgrades, and Docker Engine with
#      the compose plugin from Docker's official apt repository
#   2. creates the user `deploy` with your key, in the docker group, with
#      passwordless sudo
#   3. SSH: key-only login (passwords off); root keeps key-only login as a
#      fallback
#   4. firewall (ufw): allow 22, 80 and 443 in, deny every other port
#   5. automatic security updates (unattended-upgrades)
#   6. clones the repo to /home/deploy/job-market-tracker, creates its .env
#      from deploy/.env.example (mode 600) if missing, creates the backup
#      directory and installs the systemd units. It enables the backup
#      timer only; the daily timer is enabled at cut-over.
#
# UNTESTED on a real server: written and shellchecked in a VM without one.
set -euo pipefail

key="${1:-}"
repo_url="${2:-https://github.com/PloypairaohPat/job-market-tracker.git}"
user=deploy
home="/home/${user}"
repo="${home}/job-market-tracker"
backup_dir=/var/backups/jobmarket

say() { printf '\n== %s\n' "$*"; }
die() { echo "bootstrap: $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "run this as root (ssh root@<server>, then: bash bootstrap.sh ...)"
[ -n "$key" ] || die "usage: bash bootstrap.sh \"<your SSH public key>\" [repo-url]"
case "$key" in
    *PRIVATE* | *$'\n'*) die "that's not a public key: pass the ONE line from id_ed25519.pub, never the private key" ;;
esac
keyfile="$(mktemp)"
printf '%s\n' "$key" >"$keyfile"
ssh-keygen -l -f "$keyfile" >/dev/null 2>&1 || { rm -f "$keyfile"; die "that doesn't look like an SSH public key"; }
rm -f "$keyfile"

# shellcheck source=/dev/null
. /etc/os-release
[ "${ID:-}" = ubuntu ] || die "this script is for Ubuntu 24.04 (found ${PRETTY_NAME:-unknown})"
[ "${VERSION_ID:-}" = 24.04 ] || echo "warning: written for Ubuntu 24.04, found ${VERSION_ID:-?}" >&2

say "1. packages and Docker Engine"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get install -y -q ca-certificates curl git make ufw unattended-upgrades
if ! docker compose version >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
        "https://download.docker.com/linux/ubuntu ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
        >/etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi
systemctl enable --now docker
docker compose version

say "2. user ${user}"
id "$user" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$user"
usermod -aG docker "$user"
install -d -m 700 -o "$user" -g "$user" "${home}/.ssh"
touch "${home}/.ssh/authorized_keys"
grep -qxF -- "$key" "${home}/.ssh/authorized_keys" || printf '%s\n' "$key" >>"${home}/.ssh/authorized_keys"
chown "${user}:${user}" "${home}/.ssh/authorized_keys"
chmod 600 "${home}/.ssh/authorized_keys"
# The docker group is already root-equivalent, so a sudo password would add
# friction, not safety (parked in docs/overnight-deploy-kit.md).
echo "${user} ALL=(ALL) NOPASSWD:ALL" >"/etc/sudoers.d/90-${user}"
chmod 440 "/etc/sudoers.d/90-${user}"
visudo -cf "/etc/sudoers.d/90-${user}" >/dev/null

say "3. SSH: keys only"
# sshd keeps the FIRST value it reads for a setting, and this file sorts
# before the 50-cloud-init.conf that some images ship.
cat >/etc/ssh/sshd_config.d/10-jobmarket.conf <<'EOF'
# deploy/bootstrap.sh: key-only SSH login
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
EOF
mkdir -p /run/sshd  # sshd -t needs it; normally there while ssh runs
sshd -t
systemctl reload-or-restart ssh
sshd -T | grep -E '^(passwordauthentication|kbdinteractiveauthentication|permitrootlogin) '

say "4. firewall (ufw)"
# Docker-published ports bypass ufw. That's why db publishes no port and
# Metabase is bound to 127.0.0.1 in deploy/docker-compose.prod.yml.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose

say "5. automatic security updates"
cat >/etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
EOF
systemctl enable --now unattended-upgrades

say "6. repo, .env, backups, systemd units"
if [ -d "${repo}/.git" ]; then
    echo "${repo} already exists; left as it is (to update it: docs/deploy.md, \"Updating\")"
else
    runuser -u "$user" -- git clone "$repo_url" "$repo"
fi
env_created=0
if [ ! -f "${repo}/.env" ]; then
    install -m 600 -o "$user" -g "$user" "${repo}/deploy/.env.example" "${repo}/.env"
    env_created=1
fi
install -d -m 700 -o "$user" -g "$user" "$backup_dir"
install -m 644 "${repo}"/deploy/systemd/jobmarket-*.service "${repo}"/deploy/systemd/jobmarket-*.timer \
    /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now jobmarket-backup.timer
# jobmarket-daily.timer is deliberately NOT enabled here: the cut-over does it.

say "done"
if [ "$env_created" = 1 ]; then
    echo "Created ${repo}/.env from deploy/.env.example (mode 600)."
else
    echo "${repo}/.env already existed; left as it is."
fi
cat <<EOF

Before closing this root session, open a SECOND PowerShell window on your
laptop and check that this works:
    ssh ${user}@<server>

Then, logged in as ${user} (docs/deploy.md):
    cd ~/job-market-tracker
    nano .env                  # fill in every empty value; Ctrl+O, Enter saves, Ctrl+X exits
    make prod-build
    make prod-up

The daily timer is NOT enabled; the cut-over enables it.
EOF

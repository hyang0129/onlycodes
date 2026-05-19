#!/usr/bin/env bash
# Bring this dev container onto the huddlenet tailnet and establish ssh access to Tower.
# Idempotent: safe to re-run after container rebuilds.
#
# Requirements (set in onlycodes/.env):
#   TS_OAUTH_CLIENT_ID, TS_OAUTH_CLIENT_SECRET   — OAuth client in huddlenet with auth_keys:write
#
# After running, `ssh tower` works (assuming Serg has added ~/.ssh/tower_huddlenet.pub
# to /root/.ssh/authorized_keys on the Tower box).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

[[ -f .env ]] || { echo "missing $REPO_ROOT/.env"; exit 1; }
set -a; . ./.env; set +a
: "${TS_OAUTH_CLIENT_ID:?}"; : "${TS_OAUTH_CLIENT_SECRET:?}"

if ! command -v tailscale >/dev/null; then
  echo "[1/5] installing tailscale"
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.noarmor.gpg | sudo tee /usr/share/keyrings/tailscale-archive-keyring.gpg >/dev/null
  curl -fsSL https://pkgs.tailscale.com/stable/ubuntu/jammy.tailscale-keyring.list | sudo tee /etc/apt/sources.list.d/tailscale.list >/dev/null
  sudo apt-get update -qq
  sudo apt-get install -y tailscale netcat-openbsd >/dev/null
else
  echo "[1/5] tailscale already installed ($(tailscale version | head -1))"
fi

if ! pgrep -x tailscaled >/dev/null; then
  echo "[2/5] starting tailscaled (userspace-networking, SOCKS5 on :1055)"
  sudo mkdir -p /var/lib/tailscale /var/run/tailscale
  sudo nohup tailscaled \
    --tun=userspace-networking \
    --socks5-server=localhost:1055 \
    --outbound-http-proxy-listen=localhost:1055 \
    --state=/var/lib/tailscale/tailscaled.state \
    --socket=/var/run/tailscale/tailscaled.sock \
    >/tmp/tailscaled.log 2>&1 &
  sleep 2
else
  echo "[2/5] tailscaled already running"
fi

if ! tailscale status >/dev/null 2>&1; then
  echo "[3/5] minting ephemeral tagged auth key + bringing up"
  TOKEN=$(curl -sS -u "$TS_OAUTH_CLIENT_ID:$TS_OAUTH_CLIENT_SECRET" \
    -d 'grant_type=client_credentials' \
    https://api.tailscale.com/api/v2/oauth/token \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
  AUTHKEY=$(curl -sS -X POST \
    -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
    -d '{"capabilities":{"devices":{"create":{"reusable":false,"ephemeral":true,"preauthorized":true,"tags":["tag:cibox"]}}},"expirySeconds":3600,"description":"onlycodes ts_connect.sh"}' \
    "https://api.tailscale.com/api/v2/tailnet/-/keys" \
    | python3 -c 'import sys,json;print(json.load(sys.stdin)["key"])')
  sudo tailscale up --authkey="$AUTHKEY" --hostname=onlycodes-devbox --accept-routes=false
else
  echo "[3/5] tailscale already up ($(tailscale ip -4))"
fi

KEYPATH="$HOME/.ssh/tower_huddlenet"
if [[ ! -f "$KEYPATH" ]]; then
  echo "[4/5] generating ed25519 keypair at $KEYPATH"
  mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
  ssh-keygen -t ed25519 -f "$KEYPATH" -N '' -C "onlycodes-devbox@huddlenet"
else
  echo "[4/5] ssh keypair already present"
fi

if ! grep -q '^Host tower$' "$HOME/.ssh/config" 2>/dev/null; then
  echo "[5/5] adding 'Host tower' to ~/.ssh/config"
  cat >> "$HOME/.ssh/config" <<EOF

Host tower
  HostName 100.94.128.108
  User root
  IdentityFile $KEYPATH
  IdentitiesOnly yes
  ProxyCommand nc -X 5 -x localhost:1055 %h %p
  StrictHostKeyChecking accept-new
  UserKnownHostsFile ~/.ssh/known_hosts_huddlenet
  ServerAliveInterval 30
EOF
  chmod 600 "$HOME/.ssh/config"
else
  echo "[5/5] 'Host tower' already in ssh config"
fi

echo
echo "==== ready ===="
echo "  public key to give Serg (append to /root/.ssh/authorized_keys on Tower):"
echo
cat "${KEYPATH}.pub"
echo
echo "  then connect with:  ssh tower"

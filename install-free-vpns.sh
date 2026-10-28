#!/usr/bin/env bash
# Install the free VPN backends that need root. Run as:  sudo ./install-free-vpns.sh
set -euo pipefail

apt-get update
apt-get install -y \
  riseup-vpn \
  tor \
  i2pd \
  network-manager-openvpn-gnome \
  network-manager-wireguard \
  wireguard-tools \
  openvpn

# Cloudflare WARP (free) via official repo
if ! command -v warp-cli >/dev/null 2>&1; then
  curl -fsSL https://pkg.cloudflareclient.com/pubkey.gpg | gpg --dearmor -o /usr/share/keyrings/cloudflare-warp-archive-keyring.gpg
  echo "deb [signed-by=/usr/share/keyrings/cloudflare-warp-archive-keyring.gpg] https://pkg.cloudflareclient.com/ $(lsb_release -cs) main" \
    > /etc/apt/sources.list.d/cloudflare-client.list
  apt-get update
  apt-get install -y cloudflare-warp
fi

echo "done"

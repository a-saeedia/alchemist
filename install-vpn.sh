#!/usr/bin/env bash
# Install oc-vpn as a desktop app (and optionally start it at login).
#
#   ./install-vpn.sh              -> ~/.local/bin + application menu entry
#   ./install-vpn.sh --autostart  -> also start it when you log in
#   ./install-vpn.sh --uninstall  -> remove the launcher, entry and autostart
#
# Nothing here needs root. The tunnel is brought up by NetworkManager, whose
# polkit rules already allow the logged-in user to toggle their own VPN.
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
bin_dir="$HOME/.local/bin"
app_dir="$HOME/.local/share/applications"
auto_dir="$HOME/.config/autostart"
entry="$app_dir/oc-vpn.desktop"
auto_entry="$auto_dir/oc-vpn.desktop"

uninstall() {
  rm -f "$bin_dir/oc-vpn" "$HOME/.bun/bin/oc-vpn" "$entry" "$auto_entry"
  command -v update-desktop-database >/dev/null && update-desktop-database "$app_dir" || true
  echo "removed oc-vpn from $bin_dir and $app_dir"
}

render() {
  sed -e "s|@EXEC@|$bin_dir/oc-vpn|g" \
      -e "s|@ICON@|$here/icons/oc-vpn.svg|g" \
      "$here/packaging/oc-vpn.desktop.in"
}

have() { command -v "$1" >/dev/null 2>&1; }

case "${1:-}" in
  --uninstall)
    uninstall
    exit 0
    ;;
esac

echo "checks"
have nmcli       || { echo "  FAIL nmcli missing (install network-manager)"; exit 1; }
have openvpn     || echo "  warn openvpn binary missing -- NetworkManager needs it"
ls /usr/lib/*/NetworkManager/libnm-vpn-plugin-openvpn.so >/dev/null 2>&1 \
  || echo "  warn openvpn plugin for NetworkManager not found"
have python3     || { echo "  FAIL python3 missing"; exit 1; }
python3 -c 'import gi; gi.require_version("Gtk","3.0"); import gi.repository.Gtk' 2>/dev/null \
  || { echo "  FAIL PyGObject GTK3 missing (sudo apt install python3-gi gir1.2-gtk-3.0)"; exit 1; }
profiles="$(nmcli -t -f TYPE connection show 2>/dev/null | grep -c '^vpn$' || true)"
echo "  ok   nmcli, python3, GTK3"
echo "  ok   $profiles VPN profile(s) in NetworkManager"

mkdir -p "$bin_dir" "$app_dir"
ln -sfn "$here/oc-vpn" "$bin_dir/oc-vpn"
chmod +x "$here/oc-vpn"

# ~/.local/bin only reaches PATH through ~/.profile (login shells); ~/.bun/bin
# is already on PATH in this setup, so mirror the link there too.
extra_path_link=""
case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *)
    if [ -d "$HOME/.bun/bin" ]; then
      ln -sfn "$here/oc-vpn" "$HOME/.bun/bin/oc-vpn"
      extra_path_link="$HOME/.bun/bin/oc-vpn"
    fi
    ;;
esac

render > "$entry"
chmod 644 "$entry"
command -v update-desktop-database >/dev/null && update-desktop-database "$app_dir" || true

echo
echo "launcher : $bin_dir/oc-vpn -> $here/oc-vpn"
[ -n "$extra_path_link" ] && echo "on PATH  : $extra_path_link"
echo "menu     : $entry"

if [ "${1:-}" = "--autostart" ]; then
  mkdir -p "$auto_dir"
  render > "$auto_entry"
  chmod 644 "$auto_entry"
  echo "autostart: $auto_entry"
fi

if have desktop-file-validate; then
  desktop-file-validate "$entry" || true
fi

echo
echo "next:"
if [ "$profiles" = "0" ]; then
  echo "  no profiles yet -- import one:  nmcli connection import type openvpn file X.ovpn"
fi
echo "  oc-vpn --save-login      # store user/pass once, in NetworkManager"
echo "  oc-vpn                   # floating switch, bottom-right"
echo "  oc-vpn --status          # up/down + exit IP"

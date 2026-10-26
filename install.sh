#!/usr/bin/env bash
# Install oc-timer as a desktop app (and optionally autostart it at login).
#
#   ./install.sh              -> ~/.local/bin + application menu entry
#   ./install.sh --autostart  -> also start it (idle) when you log in
#   ./install.sh --uninstall  -> remove the launcher, entry and autostart
set -euo pipefail

here="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
bin_dir="$HOME/.local/bin"
app_dir="$HOME/.local/share/applications"
auto_dir="$HOME/.config/autostart"
entry="$app_dir/oc-timer.desktop"
auto_entry="$auto_dir/oc-timer.desktop"

uninstall() {
  rm -f "$bin_dir/oc-timer" "$HOME/.bun/bin/oc-timer" "$entry" "$auto_entry"
  command -v update-desktop-database >/dev/null && update-desktop-database "$app_dir" || true
  echo "removed oc-timer from $bin_dir and $app_dir"
}

render() {
  sed -e "s|@EXEC@|$bin_dir/oc-timer|g" \
      -e "s|@ICON@|$here/icons/oc-timer.svg|g" \
      "$here/packaging/oc-timer.desktop.in"
}

case "${1:-}" in
  --uninstall)
    uninstall
    exit 0
    ;;
esac

mkdir -p "$bin_dir" "$app_dir"
ln -sfn "$here/oc-timer" "$bin_dir/oc-timer"
chmod +x "$here/oc-timer"

# ~/.local/bin is only added to PATH by ~/.profile (login shells). If this shell
# does not see it, also drop a link in ~/.bun/bin, which is already on PATH.
extra_path_link=""
case ":$PATH:" in
  *":$bin_dir:"*) ;;
  *)
    if [ -d "$HOME/.bun/bin" ]; then
      ln -sfn "$here/oc-timer" "$HOME/.bun/bin/oc-timer"
      extra_path_link="$HOME/.bun/bin/oc-timer"
    fi
    ;;
esac
render > "$entry"
chmod 644 "$entry"
command -v update-desktop-database >/dev/null && update-desktop-database "$app_dir" || true

echo "launcher : $bin_dir/oc-timer -> $here/oc-timer"
[ -n "$extra_path_link" ] && echo "on PATH  : $extra_path_link"
echo "menu     : $entry"

if [ "${1:-}" = "--autostart" ]; then
  mkdir -p "$auto_dir"
  render > "$auto_entry"
  chmod 644 "$auto_entry"
  echo "autostart: $auto_entry (starts idle, nothing armed)"
fi

if command -v desktop-file-validate >/dev/null; then
  desktop-file-validate "$entry" || true
fi

echo
echo "run it:  oc-timer --minutes 45"
echo "         oc-timer --watch --dry-run"

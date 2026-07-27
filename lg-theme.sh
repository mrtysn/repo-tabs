#!/usr/bin/env bash
# DESC: Switch lazygit theme — swaps the managed theme block in config.yml
set -euo pipefail

CONF="$HOME/Library/Application Support/lazygit/config.yml"
THEMES="$HOME/Library/Application Support/lazygit/themes"
MARK="# --- theme (managed by lg-theme) ---"

strip_block() {  # config without the managed block (marker to end of file)
  sed '/^# --- theme (managed by lg-theme) ---$/,$d' "$CONF"
}

current() {
  awk -v m="$MARK" '$0 == m {getline; sub(/^# theme: /, ""); print; exit}' "$CONF"
}

if [[ $# -eq 0 ]]; then
  cur=$(current || true)
  echo "themes (drop more .yml files into $THEMES):"
  for f in "$THEMES"/*.yml; do
    b=$(basename "$f" .yml)
    [[ "$b" == "$cur" ]] && echo "  * $b" || echo "    $b"
  done
  [[ -n "$cur" ]] || echo "  (currently: lazygit default)"
  echo "usage: lg-theme <name> | default    (relaunch lazygit to apply)"
  exit 0
fi

name=$1
if [[ "$name" != default && ! -f "$THEMES/$name.yml" ]]; then
  echo "no theme '$name' in $THEMES" >&2
  exit 1
fi

tmp=$(mktemp)
strip_block > "$tmp"
if [[ "$name" != default ]]; then
  { echo "$MARK"; echo "# theme: $name"; cat "$THEMES/$name.yml"; } >> "$tmp"
fi
mv "$tmp" "$CONF"
echo "theme: $name — relaunch lazygit to see it"

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

GROUPS_DIR="$HOME/.config/repo-tabs"

if [[ $# -eq 0 ]]; then
  cur=$(current || true)
  echo "themes (drop more .yml files into $THEMES):"
  for f in "$THEMES"/*.yml; do
    b=$(basename "$f" .yml)
    [[ "$b" == "$cur" ]] && echo "  * $b" || echo "    $b"
  done
  [[ -n "$cur" ]] || echo "  (currently: lazygit default)"
  for g in work personal; do
    [[ -f "$GROUPS_DIR/theme-$g" ]] && echo "  $g tabs: $(cat "$GROUPS_DIR/theme-$g")"
  done
  echo "usage: lg-theme <name>|default            global theme (relaunch to apply)"
  echo "       lg-theme work|personal <name>|default   group override for repo-tabs lazy"
  exit 0
fi

if [[ "$1" == work || "$1" == personal ]]; then
  group=$1 name=${2:-}
  if [[ -z "$name" ]]; then
    echo "usage: lg-theme $group <name>|default" >&2
    exit 1
  fi
  mkdir -p "$GROUPS_DIR"
  if [[ "$name" == default ]]; then
    rm -f "$GROUPS_DIR/theme-$group"
    echo "$group tabs: global theme — takes effect on next repo-tabs lazy"
  else
    [[ -f "$THEMES/$name.yml" ]] || { echo "no theme '$name' in $THEMES" >&2; exit 1; }
    echo "$name" > "$GROUPS_DIR/theme-$group"
    echo "$group tabs: $name — takes effect on next repo-tabs lazy"
  fi
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

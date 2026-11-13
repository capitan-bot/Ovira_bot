#!/usr/bin/env bash
# CAPITAN VPN - banner (reads pre-made art from ./art)

BC='\033[1;36m'; BY='\033[1;33m'; BM='\033[1;35m'; BG='\033[1;32m'
BW='\033[1;37m'; BN='\033[0m'
_AD="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/art"

_cols() { local c; c=$(tput cols 2>/dev/null || echo 80); [ "$c" -gt 64 ] && c=64; echo "$c"; }

_center_block() {
  local cols max=0 pad l lines=()
  cols=$(_cols)
  while IFS= read -r l; do
    lines+=("$l"); (( ${#l} > max )) && max=${#l}
  done
  pad=$(( (cols - max) / 2 )); (( pad < 0 )) && pad=0
  for l in "${lines[@]}"; do printf '%*s%s\n' "$pad" "" "$l"; done
}

_center_text() {
  local s="$1" cols pad
  cols=$(_cols)
  pad=$(( (cols - ${#s}) / 2 )); (( pad < 0 )) && pad=0
  printf '%*s%s\n' "$pad" "" "$s"
}

_pick() {
  local f w cols
  cols=$(_cols)
  for f in "$@"; do
    [ -s "$f" ] || continue
    w=$(awk '{ if (length>m) m=length } END{print m+0}' "$f")
    if [ "$w" -le "$cols" ]; then cat "$f"; return 0; fi
  done
  return 1
}

show_banner() {
  local a
  echo
  if a=$(_pick "$_AD/name_big.txt" "$_AD/name_mini.txt"); then
    echo -ne "$BM"; printf '%s\n' "$a" | _center_block; echo -ne "$BN"
  else
    echo -ne "$BM"; _center_text "A M I R A L I H D T T"; echo -ne "$BN"
  fi
  echo
  if a=$(_pick "$_AD/cap_big.txt" "$_AD/cap_small.txt"); then
    echo -ne "$BC"; printf '%s\n' "$a" | _center_block; echo -ne "$BN"
  else
    echo -ne "$BC"; _center_text "C A P I T A N   V P N"; echo -ne "$BN"
  fi
  echo
  echo -ne "$BG"; _center_text "Telegram: @Amiralihdtt"; echo -ne "$BN"
  echo -ne "$BW"; _center_text "This panel is made for the Ovira panel"
  _center_text "Ovira panel creator: erfan xray"; echo -ne "$BN"
  echo
  echo -ne "$BY"; _center_text "~ Secure & Anonymous ~"; echo -ne "$BN"
  echo
}

#!/usr/bin/env bash
# CAPITAN VPN installer banner (centered)
show_banner() {
  [ "${CAPITAN_BANNER_SHOWN:-}" = "1" ] && return 0

  local cols rows
  cols=$(tput cols 2>/dev/null || echo 80)
  rows=$(tput lines 2>/dev/null || echo 24)

  local logo=(
"  ____    _    ____  ___ _____  _    _   _  __     ______  _   _ "
" / ___|  / \\  |  _ \\|_ _|_   _|/ \\  | \\ | | \\ \\   / /  _ \\| \\ | |"
"| |     / _ \\ | |_) || |  | | / _ \\ |  \\| |  \\ \\ / /| |_) |  \\| |"
"| |___ / ___ \\|  __/ | |  | |/ ___ \\| |\\  |   \\ V / |  __/| |\\  |"
" \\____/_/   \\_\\_|   |___| |_/_/   \\_\\_| \\_|    \\_/  |_|   |_| \\_|"
  )

  center() {  # usage: center "text" "color"
    local t="$1" c="$2"
    local pad=$(( (cols - ${#t}) / 2 ))
    [ "$pad" -lt 0 ] && pad=0
    printf '%b%*s%s\033[0m\n' "$c" "$pad" "" "$t"
  }

  clear 2>/dev/null || true
  local top=$(( (rows - 14) / 2 ))
  [ "$top" -lt 1 ] && top=1
  for ((i=0; i<top; i++)); do echo; done

  center "Creator: Amiralihdtt" '\033[1;32m'
  center "Telegram: @Amiralihdtt" '\033[1;32m'
  echo

  for l in "${logo[@]}"; do center "$l" '\033[1;36m'; done
  echo
  center "Secure & Anonymous" '\033[1;33m'
  echo
  center "This panel is made for the Ovira panel" '\033[0;37m'
  center "Ovira panel creator: erfan xray" '\033[0;37m'
  echo
  sleep 2
}

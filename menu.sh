#!/usr/bin/env bash
# CAPITAN VPN - main menu
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR" || exit 1

C='\033[1;36m'; Y='\033[1;33m'; R='\033[1;31m'; G='\033[1;32m'
M='\033[1;35m'; W='\033[1;37m'; D='\033[2m'; N='\033[0m'

[ -f "$DIR/banner.sh" ] && source "$DIR/banner.sh"
export CAPITAN_BANNER_SHOWN=1

bot_status() {
  if docker compose ps --status running --services 2>/dev/null | grep -qx bot; then
    echo -e "${G}● Running${N}"
  else
    echo -e "${R}● Stopped${N}"
  fi
}

line() { echo -e "${C}  ──────────────────────────────────────────${N}"; }
section() { echo -e "\n  ${M}▌ $1${N}"; }
item() { echo -e "   ${Y}$1${N}  ${W}$2${N}"; }

header() {
  clear
  if declare -f show_banner >/dev/null; then show_banner; fi
  echo
  line
  echo -e "   ${W}Bot status:${N} $(bot_status)   ${D}|  $(date '+%Y-%m-%d %H:%M')${N}"
  line
}

draw_menu() {
  section "SETUP"
  item "1" "🚀  Install"
  item "2" "❌  Uninstall"
  item "3" "🔄  Update"
  section "BACKUP & LOGS"
  item "4" "📋  Get logs"
  item "5" "📦  Get backup"
  item "6" "🔁  Add backup (restore)"
  section "SETTINGS"
  item "7" "🔑  Change bot token"
  item "8" "🆔  Change admin IDs"
  echo
  line
  item "0" "🚪  Exit"
  line
  echo
}

pause() { echo; read -r -p "$(echo -e "${D}Press Enter to go back to the menu...${N}")" _; }

do_install() {
  echo -e "${G}>> Installing...${N}"
  bash "$DIR/setup.sh"
}

do_uninstall() {
  echo -e "${R}>> Uninstall${N}"
  read -r -p "Stop and remove the bot containers? [y/N]: " a
  [[ "$a" =~ ^[Yy]$ ]] || { echo "Cancelled."; return; }

  echo -e "${Y}Your .env holds ENCRYPTION_KEY. Without it, stored panel credentials and configs are unreadable.${N}"
  read -r -p "Also DELETE the database and all data? Type DELETE to confirm, or press Enter to keep data: " b
  if [ "$b" = "DELETE" ]; then
    docker compose down -v --remove-orphans
    echo -e "${R}Containers and database volumes removed.${N}"
    read -r -p "Delete .env too? [y/N]: " c
    if [[ "$c" =~ ^[Yy]$ ]]; then rm -f .env && echo ".env removed."; fi
  else
    docker compose down --remove-orphans
    echo -e "${G}Containers removed. Database and .env kept.${N}"
  fi
}

do_update() {
  echo -e "${G}>> Updating...${N}"
  [ -d .git ] || { echo -e "${R}Not a git repository, cannot update.${N}"; return; }
  [ -f .env ] && cp .env ".env.backup.$(date +%Y%m%d%H%M%S)"
  if ! git pull --ff-only; then
    echo -e "${R}git pull failed (local changes or conflict). Nothing was changed.${N}"
    return
  fi
  docker compose run --rm migrate || { echo -e "${R}Migration failed, bot not restarted.${N}"; return; }
  docker compose up -d --build bot
  echo -e "${G}Update finished.${N}"
  docker compose logs --tail 15 bot
}

do_logs()    { bash "$DIR/backup_tools.sh" logs; }
do_backup()  { bash "$DIR/backup_tools.sh" backup; }
do_restore() { bash "$DIR/backup_tools.sh" restore; }
do_token()   { bash "$DIR/config_tools.sh" token; }
do_admins()  { bash "$DIR/config_tools.sh" admins; }

while true; do
  header
  draw_menu
  read -r -p "$(echo -e "${C}  ➜ Select [0-8]: ${N}")" choice
  echo
  case "$choice" in
    1) do_install;   pause ;;
    2) do_uninstall; pause ;;
    3) do_update;    pause ;;
    4) do_logs;      pause ;;
    5) do_backup;    pause ;;
    6) do_restore;   pause ;;
    7) do_token;     pause ;;
    8) do_admins;    pause ;;
    0) echo -e "${G}Bye 👋${N}"; exit 0 ;;
    *) echo -e "${R}Invalid choice.${N}"; sleep 1 ;;
  esac
done

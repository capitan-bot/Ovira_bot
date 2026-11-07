#!/usr/bin/env bash
# CAPITAN VPN - main menu
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
cd "$DIR" || exit 1

[ -f "$DIR/banner.sh" ] && source "$DIR/banner.sh" && show_banner
export CAPITAN_BANNER_SHOWN=1

C='\033[1;36m'; Y='\033[1;33m'; R='\033[1;31m'; G='\033[1;32m'; N='\033[0m'

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

while true; do
  echo
  echo -e "${C}  1) Install${N}"
  echo -e "${C}  2) Uninstall${N}"
  echo -e "${C}  3) Update${N}"
  echo -e "${C}  0) Exit${N}"
  echo
  read -r -p "Select [0-3]: " choice
  case "$choice" in
    1) do_install ;;
    2) do_uninstall ;;
    3) do_update ;;
    0) exit 0 ;;
    *) echo "Invalid choice." ;;
  esac
done

#!/usr/bin/env bash
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR" || exit 1
[ -f .env ] || { echo "❌ فایل .env پیدا نشد"; exit 1; }

setenv() {  # setenv KEY VALUE
  local k="$1" v="$2" esc
  esc=$(printf '%s' "$v" | sed -e 's/[\\|&]/\\&/g')
  if grep -q "^$k=" .env; then sed -i "s|^$k=.*|$k=$esc|" .env
  else printf '\n%s=%s\n' "$k" "$v" >> .env; fi
}
getenv() { grep -m1 "^$1=" .env | cut -d= -f2- | tr -d '\r'; }
backup_env() { cp .env ".env.backup.$(date +%Y%m%d%H%M%S)"; chmod 600 .env; }
restart_bot() {
  docker compose up -d --force-recreate bot
  sleep 6; docker compose logs --tail=15 bot
}

change_token() {
  local t me
  echo "توکن فعلی: $(getenv BOT_TOKEN | cut -c1-10)..."
  read -rp "🤖 توکن جدید (Enter = لغو): " t </dev/tty
  t=$(printf '%s' "$t" | tr -d '[:space:]')
  [ -z "$t" ] && { echo "لغو شد"; return 0; }
  [[ "$t" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$ ]] || { echo "❌ فرمت توکن درست نیست"; return 1; }
  me=$(curl -s "https://api.telegram.org/bot${t}/getMe")
  if ! echo "$me" | grep -q '"ok":true'; then echo "❌ تلگرام این توکن رو قبول نکرد"; return 1; fi
  echo "✅ ربات: @$(echo "$me" | grep -o '"username":"[^"]*"' | cut -d'"' -f4)"
  backup_env
  setenv BOT_TOKEN "$t"
  restart_bot
}

change_admins() {
  local a
  echo "ادمین‌های فعلی: $(getenv ADMIN_TELEGRAM_IDS)"
  read -rp "🆔 آیدی عددی جدید (چندتا با کاما، Enter = لغو): " a </dev/tty
  a=$(printf '%s' "$a" | tr -d '[:space:]')
  [ -z "$a" ] && { echo "لغو شد"; return 0; }
  [[ "$a" =~ ^[0-9]+(,[0-9]+)*$ ]] || { echo "❌ فقط عدد و کاما"; return 1; }
  backup_env
  setenv ADMIN_TELEGRAM_IDS "$a"
  restart_bot
}

case "${1:-}" in
  token) change_token;;
  admins) change_admins;;
  *) echo "usage: $0 token|admins";;
esac

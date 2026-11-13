#!/usr/bin/env bash
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"
BK="$DIR/backups"; mkdir -p "$BK"
command -v zip >/dev/null && command -v unzip >/dev/null || apt-get install -y zip unzip >/dev/null

envget() { grep -m1 "^$1=" "$DIR/.env" | cut -d= -f2- | tr -d '\r'; }

send_file() {
  local f="$1" cap="$2" token ids id ok=1 arr
  token=$(envget BOT_TOKEN); ids=$(envget ADMIN_TELEGRAM_IDS)
  IFS=',' read -ra arr <<< "$ids"
  for id in "${arr[@]}"; do
    if curl -s --form-string chat_id="$id" --form-string caption="$cap" \
       -F document=@"$f" "https://api.telegram.org/bot${token}/sendDocument" | grep -q '"ok":true'; then
      echo "✅ ارسال شد به $id"; ok=0
    else echo "❌ ارسال به $id ناموفق (حداکثر حجم ۵۰ مگابایت)"; fi
  done
  return $ok
}

do_logs() {
  local f="$BK/logs_$(date +%Y%m%d_%H%M%S).txt"
  docker compose logs --no-color --tail=300 bot > "$f" 2>&1
  send_file "$f" "📋 لاگ ربات"
}

make_backup() {
  local ts tmp out u d
  ts=$(date +%Y%m%d_%H%M%S); tmp=$(mktemp -d); out="$BK/capitan_backup_$ts.zip"
  u=$(envget POSTGRES_USER); d=$(envget POSTGRES_DB)
  if ! docker compose exec -T db pg_dump -U "$u" -d "$d" --clean --if-exists --no-owner > "$tmp/db.sql"; then
    echo "❌ گرفتن دیتابیس ناموفق بود" >&2; rm -rf "$tmp"; return 1
  fi
  cp .env "$tmp/env.backup"
  [ -d storage ] && cp -r storage "$tmp/storage"
  (cd "$tmp" && zip -qr "$out" .)
  rm -rf "$tmp"; echo "$out"
}

do_backup() {
  local f; f=$(make_backup) || return 1
  echo "📦 $f"
  send_file "$f" "📦 بکاپ CAPITAN $(date '+%Y-%m-%d %H:%M')"
}

do_restore() {
  local name f c safety tmp sql u d k v
  echo "فایل .zip یا .sql رو توی $BK بذار (یا مسیر کامل بده)"
  ls -1 "$BK" 2>/dev/null | grep -Ei '\.(zip|sql)$' | tail -10
  read -rp "📂 اسم فایل: " name </dev/tty
  name=$(printf '%s' "$name" | tr -d '\r\n')
  [ -z "$name" ] && return 0
  case "$name" in /*) f="$name";; *) f="$BK/$name";; esac
  [ -f "$f" ] || { echo "❌ فایل پیدا نشد: $f"; return 1; }
  case "${f,,}" in *.zip|*.sql) ;; *) echo "❌ فقط zip یا sql"; return 1;; esac

  tmp=$(mktemp -d)
  if [[ "${f,,}" == *.zip ]]; then
    unzip -q "$f" -d "$tmp" || { echo "❌ زیپ خراب است"; rm -rf "$tmp"; return 1; }
    sql="$tmp/db.sql"
    [ -f "$sql" ] || sql=$(find "$tmp" -maxdepth 2 -iname '*.sql' | head -1)
  else
    sql="$f"
  fi
  [ -n "${sql:-}" ] && [ -f "$sql" ] || { echo "❌ فایل sql داخل بکاپ نبود"; rm -rf "$tmp"; return 1; }

  read -rp "⚠️ دیتابیس فعلی پاک و جایگزین میشه. بنویس yes: " c </dev/tty
  [ "$c" = "yes" ] || { echo "لغو شد"; rm -rf "$tmp"; return 0; }

  safety=$(make_backup) || { echo "❌ بکاپ ایمنی نشد، لغو شد"; rm -rf "$tmp"; return 1; }
  echo "🛟 بکاپ ایمنی از وضعیت فعلی: $safety"

  u=$(envget POSTGRES_USER); d=$(envget POSTGRES_DB)
  docker compose stop bot
  if docker compose exec -T db psql -U "$u" -d "$d" -v ON_ERROR_STOP=1 -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" \
     && docker compose exec -T db psql -U "$u" -d "$d" -v ON_ERROR_STOP=1 < "$sql" >/dev/null; then
    echo "✅ دیتابیس ریخته شد"
  else
    echo "❌ ریستور خطا داد. برای برگشت، همین ابزار رو با فایل $safety اجرا کن."
    rm -rf "$tmp"; return 1
  fi

  if [ -d "$tmp/storage" ]; then mkdir -p storage; cp -r "$tmp/storage/." storage/; fi
  if [ -f "$tmp/env.backup" ]; then
    for k in ENCRYPTION_KEY JWT_SECRET; do
      v=$(grep -m1 "^$k=" "$tmp/env.backup" | cut -d= -f2-)
      [ -n "$v" ] && sed -i "s|^$k=.*|$k=$v|" .env
    done
    echo "🔑 ENCRYPTION_KEY و JWT_SECRET از بکاپ برگردانده شد"
  fi
  rm -rf "$tmp"
  docker compose up -d
  sleep 6; docker compose logs --tail=15 bot
  echo "🎉 ریستور تمام شد"
}

case "${1:-}" in
  logs) do_logs;;
  backup) do_backup;;
  restore) do_restore;;
  *) echo "usage: $0 logs|backup|restore";;
esac

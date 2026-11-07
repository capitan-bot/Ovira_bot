#!/usr/bin/env bash
# shellcheck disable=SC1091
[ -f "$(dirname "$0")/banner.sh" ] && source "$(dirname "$0")/banner.sh" && show_banner
set -euo pipefail
REPO_URL="https://github.com/capitan-bot/Ovira_bot.git"
DIR=/opt/capitan

[ "$(id -u)" -eq 0 ] || { echo "❌ با کاربر root اجرا کنید (sudo -i)"; exit 1; }
echo "====== CAPITAN VPN installer ======"

apt-get update -y >/dev/null
apt-get install -y git curl openssl ca-certificates >/dev/null
command -v docker >/dev/null 2>&1 || curl -fsSL https://get.docker.com | sh

if [ -d "$DIR/.git" ]; then git -C "$DIR" pull --ff-only; else git clone "$REPO_URL" "$DIR"; fi
cd "$DIR"
mkdir -p storage

ask() { local v; read -rp "$2" v </dev/tty; printf '%s' "$v" | tr -d '\r\n'; }

if [ -f .env ]; then
  echo "ℹ️ فایل .env از قبل هست؛ فقط آپدیت و اجرا می‌شود."
else
  while true; do
    BOT_TOKEN=$(ask x "🤖 توکن ربات (از BotFather): " | tr -d '[:space:]')
    [[ "$BOT_TOKEN" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$ ]] && break
    echo "❌ فرمت توکن درست نیست."
  done
  while true; do
    ADMIN_IDS=$(ask x "🆔 آیدی عددی ادمین (چندتا با کاما): " | tr -d '[:space:]')
    [[ "$ADMIN_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]] && break
    echo "❌ فقط عدد."
  done
  SHOP=$(ask x "🏪 نام فروشگاه [CAPITAN VPN]: "); SHOP=${SHOP:-CAPITAN VPN}
  CARD=$(ask x "💳 شماره کارت (Enter = رد): ")
  HOLDER=$(ask x "👤 نام صاحب کارت (Enter = رد): ")
  SUPPORT=$(ask x "🎧 آیدی پشتیبانی مثل @support (Enter = رد): ")
  LOGGID=$(ask x "📋 آیدی گروه لاگ (مثل -100123..., Enter = رد): " | tr -d '[:space:]')

  PGU=capitan; PGDB=capitan
  PGP=$(openssl rand -hex 16)
  ENC=$(openssl rand -base64 32 | tr '+/' '-_')
  JWT=$(openssl rand -hex 32)
  if grep -qi asyncpg requirements.txt; then DRV=asyncpg; else DRV=psycopg; fi

  cat > .env <<ENVEOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_TELEGRAM_IDS=$ADMIN_IDS

POSTGRES_USER=$PGU
POSTGRES_PASSWORD=$PGP
POSTGRES_DB=$PGDB
DATABASE_URL=postgresql+$DRV://$PGU:$PGP@db:5432/$PGDB

ENCRYPTION_KEY=$ENC
JWT_SECRET=$JWT

SEED_SHOP_NAME=$SHOP
SEED_CARD_NUMBER=$CARD
SEED_CARD_HOLDER=$HOLDER
SEED_SUPPORT_ID=$SUPPORT
LOG_GROUP_ID=${LOGGID:-0}
ENVEOF
  chmod 600 .env
  echo "✅ فایل .env ساخته شد."
fi

docker compose up -d --build
sleep 8
docker compose logs --tail=15 bot
echo "🎉 نصب تمام شد. توی ربات /admin رو بزن."

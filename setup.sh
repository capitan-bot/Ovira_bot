#!/usr/bin/env bash
# CAPITAN VPN - interactive installer. Run: bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "======================================"
echo " CAPITAN VPN - نصب خودکار"
echo "======================================"

# --- Docker ---
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker نصب نیست؛ در حال نصب..."
  curl -fsSL https://get.docker.com | sh
fi

# --- OpenSSL ---
if ! command -v openssl >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y openssl
fi

# --- Existing .env ---
if [ -f .env ]; then
  read -rp "فایل .env از قبل وجود دارد. دوباره ساخته شود؟ (y/N): " ow
  if [[ "${ow,,}" != "y" ]]; then
    echo "از همان .env موجود استفاده می‌شود."
    docker compose up -d db
    docker compose run --rm migrate
    docker compose up -d --build bot
    exit 0
  fi
fi

# --- Ask bot token ---
while true; do
  read -rp "🤖 توکن ربات را وارد کنید (از BotFather): " BOT_TOKEN
  BOT_TOKEN="$(echo -n "$BOT_TOKEN" | tr -d '[:space:]')"
  if [[ "$BOT_TOKEN" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$ ]]; then break; fi
  echo "❌ فرمت توکن درست نیست. مثال: 123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
done

# --- Ask admin numeric id ---
while true; do
  read -rp "🆔 آیدی عددی ادمین را وارد کنید (چند ادمین با کاما مثل 123,456): " ADMIN_IDS
  ADMIN_IDS="$(echo -n "$ADMIN_IDS" | tr -d '[:space:]')"
  if [[ "$ADMIN_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]]; then break; fi
  echo "❌ آیدی عددی باید فقط عدد باشد (مثلاً 7010190804)."
done

# --- Optional shop info ---
read -rp "🏪 نام فروشگاه [CAPITAN VPN]: " SHOP
SHOP="${SHOP:-CAPITAN VPN}"
read -rp "💳 شماره کارت (Enter = رد کردن): " CARD
HOLDER=""
read -rp "🎧 آیدی پشتیبانی تلگرام، مثل @support (Enter = رد کردن): " SUPPORT

clean() { printf '%s' "$1" | LC_ALL=C tr -cd '\040-\176'; }
SHOP="$(clean "$SHOP")"
CARD="$(clean "$CARD")"
SUPPORT="$(clean "$SUPPORT")"
[ -z "$SHOP" ] && SHOP="CAPITAN VPN"

# --- Generate secrets ---
echo "در حال ساخت کلیدهای امنیتی..."
ENC_KEY="$(openssl rand -hex 32)"
JWT_SECRET="$(openssl rand -hex 32)"

# --- Create .env file ---
cat > .env << ENVEOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_IDS=$ADMIN_IDS
SHOP_NAME=$SHOP
CARD_NUMBER=$CARD
CARD_HOLDER=$HOLDER
SUPPORT_USERNAME=$SUPPORT
ENCRYPTION_KEY=$ENC_KEY
JWT_SECRET_KEY=$JWT_SECRET
DATABASE_URL=sqlite+aiosqlite:///storage/database.db
DEBUG=false
ENVEOF
chmod 600 .env
echo "✅ فایل .env با موفقیت ایجاد شد."

# --- Run Docker ---
echo "در حال راه‌اندازی سرویس‌ها با Docker..."
docker compose up -d db
docker compose run --rm migrate
docker compose up -d --build bot

echo "======================================"
echo "🎉 نصب و راه‌اندازی ربات با موفقیت به اتمام رسید!"
echo "======================================"

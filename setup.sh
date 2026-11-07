#!/usr/bin/env bash
# CAPITAN VPN - installer. Run: bash setup.sh
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
if ! docker compose version >/dev/null 2>&1; then
  echo "❌ docker compose پیدا نشد. Docker را به‌روز کنید."
  exit 1
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
    docker compose up -d --build
    exit 0
  fi
  # new .env means new DB password: old volume would reject it
  echo "⚠️ ساخت دوبارهٔ .env دیتابیس قبلی را پاک می‌کند."
  read -rp "ادامه می‌دهید؟ (y/N): " ok
  [[ "${ok,,}" == "y" ]] || exit 0
  docker compose down -v 2>/dev/null || true
fi

# --- Bot token ---
while true; do
  read -rp "🤖 توکن ربات را وارد کنید (از BotFather): " BOT_TOKEN
  BOT_TOKEN="$(echo -n "$BOT_TOKEN" | tr -d '[:space:]')"
  if [[ "$BOT_TOKEN" =~ ^[0-9]{6,12}:[A-Za-z0-9_-]{30,}$ ]]; then break; fi
  echo "❌ فرمت توکن درست نیست."
done

# --- Admin id ---
while true; do
  read -rp "🆔 آیدی عددی ادمین (چند ادمین با کاما): " ADMIN_IDS
  ADMIN_IDS="$(echo -n "$ADMIN_IDS" | tr -d '[:space:]')"
  if [[ "$ADMIN_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]]; then break; fi
  echo "❌ آیدی عددی باید فقط عدد باشد."
done

# --- Optional shop info ---
clean() { printf '%s' "$1" | LC_ALL=C tr -cd '\040-\176'; }
read -rp "🏪 نام فروشگاه [CAPITAN VPN]: " SHOP
read -rp "💳 شماره کارت (Enter = رد کردن): " CARD
read -rp "👤 نام صاحب کارت (Enter = رد کردن): " HOLDER
read -rp "🎧 آیدی پشتیبانی مثل @support (Enter = رد کردن): " SUPPORT
SHOP="$(clean "${SHOP:-CAPITAN VPN}")"
CARD="$(clean "$CARD")"
HOLDER="$(clean "$HOLDER")"
SUPPORT="$(clean "$SUPPORT")"

# --- Secrets ---
echo "در حال ساخت کلیدهای امنیتی..."
DB_PASS="$(openssl rand -hex 16)"
ENC_KEY="$(openssl rand -hex 32)"
JWT="$(openssl rand -hex 32)"

umask 077
cat > .env << ENVEOF
BOT_TOKEN=$BOT_TOKEN
ADMIN_TELEGRAM_IDS=$ADMIN_IDS

POSTGRES_USER=capitan
POSTGRES_PASSWORD=$DB_PASS
POSTGRES_DB=capitan
DATABASE_URL=postgresql+asyncpg://capitan:$DB_PASS@db:5432/capitan

ENCRYPTION_KEY=$ENC_KEY
JWT_SECRET=$JWT

SEED_SHOP_NAME=$SHOP
SEED_CARD_NUMBER=$CARD
SEED_CARD_HOLDER=$HOLDER
SEED_SUPPORT_ID=$SUPPORT
LOG_GROUP_ID=
ENVEOF
echo "✅ فایل .env ساخته شد."

# --- Run ---
echo "در حال راه‌اندازی سرویس‌ها..."
mkdir -p storage
if ! docker compose up -d --build; then
  echo "❌ راه‌اندازی ناموفق بود. لاگ‌ها:"
  docker compose logs --tail 40
  exit 1
fi

# --- Verify bot is really running ---
sleep 8
if [ "$(docker compose ps --status running --services | grep -c '^bot$')" -ne 1 ]; then
  echo "❌ ربات بالا نیامد. لاگ ربات:"
  docker compose logs bot --tail 40
  exit 1
fi

echo "======================================"
echo "🎉 نصب با موفقیت انجام شد و ربات در حال اجراست."
echo "======================================"

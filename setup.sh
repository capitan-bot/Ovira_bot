#!/usr/bin/env bash
# CAPITAN VPN - interactive installer. Run:  bash setup.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "======================================"
echo "   CAPITAN VPN - نصب خودکار"
echo "======================================"

# --- Docker ---
if ! command -v docker >/dev/null 2>&1; then
  echo "Docker نصب نیست؛ در حال نصب..."
  curl -fsSL https://get.docker.com | sh
fi
command -v openssl >/dev/null 2>&1 || { apt-get update -y && apt-get install -y openssl; }

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
  echo "❌ فرمت توکن درست نیست. مثال: 123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
done

# --- Ask admin numeric id ---
while true; do
  read -rp "🆔 آیدی عددی ادمین را وارد کنید (چند ادمین: با کاما جدا کنید): " ADMIN_IDS
  ADMIN_IDS="$(echo -n "$ADMIN_IDS" | tr -d '[:space:]')"
  if [[ "$ADMIN_IDS" =~ ^[0-9]+(,[0-9]+)*$ ]]; then break; fi
  echo "❌ آیدی عددی باید فقط عدد باشد (مثلاً 7010190804)."
done

# --- Optional shop info ---
read -rp "🏪 نام فروشگاه [CAPITAN VPN]: " SHOP; SHOP="${SHOP:-CAPITAN VPN}"
read -rp "💳 شماره کارت (Enter = رد کردن، بعداً از پنل قابل تغییر): " CARD
HOLDER=""   # Persian text is set later inside Telegram: /setcard
read -rp "🎧 آیدی پشتیبانی تلگرام، مثل @support (Enter = رد کردن): " SUPPORT

clean() { printf '%s' "$1" | LC_ALL=C tr -cd '\040-\176'; }
SHOP="$(clean "$SHOP")"; CARD="$(clean "$CARD")"; SUPPORT="$(clean "$SUPPORT")"
[ -z "$SHOP" ] && SHOP="CAPITAN VPN"

# --- Generate secrets ---
echo "در حال ساخت کلیدهای امنیتی..."
ENC_KEY="$(docker run --rm python:3.12-slim sh -c "pip install -q cryptography >/dev/null 2>&1 && python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())'")"
JWT="$(openssl rand -hex 32)"
DBPASS="$(openssl rand -hex 16)"

cat > .env <<ENV
BOT_TOKEN=${BOT_TOKEN}
ADMIN_TELEGRAM_IDS=${ADMIN_IDS}

POSTGRES_USER=capitan
POSTGRES_PASSWORD=${DBPASS}
POSTGRES_DB=capitan
DATABASE_URL=postgresql+asyncpg://capitan:${DBPASS}@db:5432/capitan

ENCRYPTION_KEY=${ENC_KEY}
JWT_SECRET=${JWT}

SEED_SHOP_NAME=${SHOP}
SEED_CARD_NUMBER=${CARD}
SEED_CARD_HOLDER=${HOLDER}
SEED_SUPPORT_ID=${SUPPORT}
ENV
chmod 600 .env

mkdir -p backup
cp .env backup/.env.backup && chmod 600 backup/.env.backup

echo "در حال راه‌اندازی دیتابیس..."
docker compose up -d db
docker compose run --rm migrate
docker compose up -d --build bot

echo
echo "✅ نصب کامل شد و ربات روشن است."
echo "⚠️  از فایل backup/.env.backup (مخصوصاً ENCRYPTION_KEY) یک نسخه جای امن نگه دارید."

# CAPITAN VPN — Stage 1: Database & Architecture

## What's in this stage
- Project skeleton (bot / backend / adapters / admin / database / workers)
- PostgreSQL schema (SQLAlchemy 2.0 async) + Alembic baseline migration
- Atomic wallet ledger (row lock + idempotency keys) — `backend/services/wallet.py`
- Invoices with unique payable amount (DB partial unique index) and
  once-only receipt approval — `backend/services/invoices.py`
- Fernet encryption for panel credentials and stored config files — `config/crypto.py`
- Panel adapter contract (`adapters/base.py`). **Real adapters come in stages 4–5.**
- Idempotent seed for editable settings (card info, texts, test limits)
- Tests (wallet, invoices, crypto)

## Quick setup
```bash
bash setup.sh   # asks for bot token + admin numeric ID, generates all keys, starts DB
```

## Manual setup
```bash
cp .env.example .env
# 1) Revoke the old bot token in @BotFather (/revoke) and paste the NEW one in BOT_TOKEN
# 2) Generate secrets and paste into .env:
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"   # ENCRYPTION_KEY
python -c "import secrets;print(secrets.token_urlsafe(48))"                               # JWT_SECRET
# 3) Use the same strong password in POSTGRES_PASSWORD and DATABASE_URL

docker compose up -d db
docker compose run --rm migrate      # alembic upgrade head + seed
```
**Back up ENCRYPTION_KEY.** Losing it makes stored panel credentials and config files unreadable.

## Tests (local)
```bash
pip install -r requirements.txt
pytest
```
Tests use in-memory SQLite. Row locks (`FOR UPDATE`) only take effect on PostgreSQL; the
production guarantees (unique amount, single approval, non-negative balance) are enforced by
DB constraints and guarded UPDATEs, which work on both.

## Design decisions
- Money = integer Toman. The random invoice extra is never credited to the wallet or counted in prices.
- Wallet changes only through `apply_wallet_change` → one ledger row per change, `CHECK balance >= 0`.
- Receipt approval is one `UPDATE ... WHERE status='pending' RETURNING`, so double-approval is impossible.
- Rejected receipt → invoice returns to `pending`, user can resend until it expires.
- Panel pricing/limits live on the `panels` row; texts/card/test rules live in `settings`. Nothing hard-coded.
- Config files are stored encrypted, byte-for-byte, with the panel's original filename.
- Admin IDs come from `ADMIN_TELEGRAM_IDS`; the dashboard login (stage 8) is separate.

## Panel status (honest notes)
- **Sanaei (3x-ui)**: adapter planned for stage 5; I will verify endpoints against the installed version's API.
- **Panel one (OpenVPN/WireGuard)**: still need the exact panel name/version to read its real API. No adapter is faked.

## Next: Stage 2 — Telegram bot, main menu, user registration, block middleware

---
## Stage 2 — Telegram bot (added)
- `bot/main.py` — aiogram 3 polling; notifies admins at startup
- Middlewares: one DB transaction per update; auto-registration + wallet creation; blocked users stopped; admin flag from `ADMIN_TELEGRAM_IDS`
- Main menu (5 buttons), wallet view (real balance), other sections show an honest "not active yet"
- Admin commands in Telegram: `/admin`, `/settings`, `/setcard`, `/setsupport`, `/setshop`; any user: `/id`
- FSM state is in memory for now (a restart resets half-finished flows).

### Update an existing server
```bash
cd /root && unzip -o "capitan_stage2.zip"     # .env is NOT overwritten
cd capitan
docker compose run --rm migrate
docker compose up -d --build bot
docker compose logs -f bot                   # Ctrl+C to leave logs
```

---
## Stage 3 — Wallet top-up (card to card)
Flow: wallet → charge → amount → invoice (unique payable amount) → receipt photo → admins get photo +
✅/❌ → approve credits **only the base amount** (once) / reject asks for a reason, user may resend.
- Admin commands: `/pending`, `/setcharge MIN MAX`, `/setextra MIN MAX`
- Unpaid invoices expire automatically (every 5 min), freeing their reserved amounts.
- The same receipt image can't be submitted twice (Telegram `file_unique_id`).
- Update: `unzip -o capitan_stage3.zip && cd capitan && docker compose run --rm migrate && docker compose up -d --build bot`

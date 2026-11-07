import asyncio
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select

from backend.services.users import audit
from bot.filters import AdminOnly, InputAction, not_command
from bot.keyboards.admin import kb
from bot.states.states import AdminStates
from bot.utils import edit_or_answer
from database.models import User

log = logging.getLogger(__name__)
router = Router()
router.message.filter(AdminOnly())
router.callback_query.filter(AdminOnly())
_tasks: set[asyncio.Task] = set()   # keep references so tasks aren't garbage collected


@router.callback_query(F.data == "adm:bc")
async def bc_start(cb: CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.input)
    await state.set_data({"action": "bc_compose"})
    await edit_or_answer(cb, "📢 پیام همگانی\n\nپیام خود را بفرستید (متن، عکس، ویدیو، فایل ...). "
                             "قبل از ارسال، پیش‌نمایش و تأیید می‌گیرید.", kb([("🔙 انصراف", "adm:home")]))
    await cb.answer()


@router.message(InputAction("bc_compose"), not_command)
async def bc_preview(message: Message, session, state: FSMContext, bot: Bot):
    total = (await session.execute(select(func.count()).select_from(User).where(User.is_blocked.is_(False)))).scalar_one()
    await state.update_data(action="bc_confirm", chat_id=message.chat.id, message_id=message.message_id)
    await message.answer("👇 پیش‌نمایش پیام:")
    await bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    await message.answer(f"این پیام برای {total:,} کاربر (غیرمسدود) ارسال می‌شود. تأیید می‌کنید؟",
                         reply_markup=kb([(f"✅ ارسال به {total:,} کاربر", "adm:bcgo")], [("❌ انصراف", "adm:home")]))


async def _run(bot: Bot, ids: list[int], from_chat: int, msg_id: int, report_chat: int) -> None:
    ok = fail = 0
    for tg_id in ids:
        for attempt in (1, 2):
            try:
                await bot.copy_message(tg_id, from_chat, msg_id)
                ok += 1
                break
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                if attempt == 2:
                    fail += 1
            except TelegramForbiddenError:
                fail += 1
                break
            except Exception as e:
                log.warning("broadcast to %s failed: %s", tg_id, e)
                fail += 1
                break
        await asyncio.sleep(0.05)   # ~20 msg/s, below Telegram's limit
    try:
        await bot.send_message(report_chat, f"📢 ارسال همگانی تمام شد.\n✅ موفق: {ok:,}\n❌ ناموفق: {fail:,}")
    except Exception:
        log.exception("broadcast report failed")


@router.callback_query(F.data == "adm:bcgo")
async def bc_go(cb: CallbackQuery, session, state: FSMContext, bot: Bot):
    data = await state.get_data()
    if data.get("action") != "bc_confirm":
        await cb.answer("این درخواست منقضی شده است.", show_alert=True)
        return
    await state.clear()
    ids = list((await session.execute(select(User.telegram_id).where(User.is_blocked.is_(False)))).scalars())
    await audit(session, f"admin:{cb.from_user.id}", "broadcast", details={"recipients": len(ids)})
    task = asyncio.create_task(_run(bot, ids, data["chat_id"], data["message_id"], cb.message.chat.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    await edit_or_answer(cb, f"⏳ ارسال برای {len(ids):,} کاربر شروع شد. پایان که رسید گزارش می‌دهم.",
                         kb([("🔙 پنل مدیریت", "adm:home")]))
    await cb.answer()

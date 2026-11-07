from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext

from bot.states.states import AdminStates


class AdminOnly(BaseFilter):
    async def __call__(self, event, is_admin: bool = False) -> bool:
        return is_admin


class InputAction(BaseFilter):
    """Matches when an admin is in the generic input state and the stored action equals one of `names`."""

    def __init__(self, *names: str):
        self.names = set(names)

    async def __call__(self, event, state: FSMContext, is_admin: bool = False):
        if not is_admin or await state.get_state() != AdminStates.input.state:
            return False
        action = (await state.get_data()).get("action", "")
        return {"action": action} if action in self.names else False


def not_command(message) -> bool:
    """For handlers that accept any content type (photo/video/text) except /commands."""
    return not ((message.text or message.caption or "").startswith("/"))

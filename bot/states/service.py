from aiogram.fsm.state import State, StatesGroup


class RenewStates(StatesGroup):
    gb = State()
    days = State()


class DeleteStates(StatesGroup):
    reason = State()

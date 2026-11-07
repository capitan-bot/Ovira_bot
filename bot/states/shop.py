from aiogram.fsm.state import State, StatesGroup


class BuyStates(StatesGroup):
    gb = State()
    days = State()
    username = State()

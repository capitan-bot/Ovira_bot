from aiogram.fsm.state import State, StatesGroup


class ChargeStates(StatesGroup):
    amount = State()
    receipt = State()


class AdminStates(StatesGroup):
    reject_reason = State()
    input = State()      # generic admin text input; the "action" key in FSM data says what is expected

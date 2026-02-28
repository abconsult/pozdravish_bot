from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from bot.config import OCCASIONS, FONTS_LIST, STYLES, PACKAGES

def build_occasion_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text=OCCASIONS[0]), KeyboardButton(text=OCCASIONS[1])],
        [KeyboardButton(text=OCCASIONS[2]), KeyboardButton(text=OCCASIONS[3])],
        [KeyboardButton(text=OCCASIONS[4]), KeyboardButton(text=OCCASIONS[5])],
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите повод",
    )

def build_font_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text=FONTS_LIST[0]), KeyboardButton(text=FONTS_LIST[1])],
        [KeyboardButton(text=FONTS_LIST[2]), KeyboardButton(text=FONTS_LIST[3])]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите шрифт",
    )

def build_style_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        [KeyboardButton(text=STYLES[0]), KeyboardButton(text=STYLES[1])],
        [KeyboardButton(text=STYLES[2]), KeyboardButton(text=STYLES[3])],
        [KeyboardButton(text=STYLES[4]), KeyboardButton(text=STYLES[5])]
    ]
    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Выберите стиль",
    )

def build_packages_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for n in (3, 5, 10):
        p = PACKAGES[n]
        word = "открытки" if n == 3 else "открыток"
        buttons.append([InlineKeyboardButton(
            text=f"{n} {word} — {p['rub']} руб.",
            callback_data=f"buy:{n}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_text_mode_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✨ Сгенерировать ИИ")],
            [KeyboardButton(text="✏️ Написать свой текст")]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

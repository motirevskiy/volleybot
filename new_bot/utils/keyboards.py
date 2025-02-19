from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Tuple, Union
from datetime import datetime
from new_bot.types import Training

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает основное меню"""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📝 Записаться", callback_data="sign_up_training"),
        InlineKeyboardButton(" Записать друга", callback_data="invite_friend")
    )
    markup.row(
        InlineKeyboardButton("📋 Мои тренировки", callback_data="my_trainings"),
        InlineKeyboardButton("📊 Расписание", callback_data="get_schedule"),
    )
    markup.add(InlineKeyboardButton("🎫 Автозапись", callback_data="auto_signup"))
    markup.add(InlineKeyboardButton("Получить права администратора", callback_data="request_admin"))
    markup.add(InlineKeyboardButton("Отписаться от рассылки", callback_data="cancel_message_sign_up"))
    return markup

def get_admin_menu_keyboard() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("➕ Создать", callback_data="create_training"),
        InlineKeyboardButton("✏️ Изменить", callback_data="edit_training"),
        InlineKeyboardButton("❌ Удалить", callback_data="delete_training"),
    )
    markup.row(
        InlineKeyboardButton("🔓 Открыть запись", callback_data="open_training_sign_up"),
        InlineKeyboardButton("🔒 Закрыть запись", callback_data="close_training")
    )
    markup.row(
        InlineKeyboardButton("📊 Расписание", callback_data="get_schedule"),
        InlineKeyboardButton("👤 Удалить участника", callback_data="remove_participant")
    )
    markup.add(InlineKeyboardButton("💳 Установить реквизиты", callback_data="set_payment_details"))
    markup.add(InlineKeyboardButton("👥 Лимит приглашений", callback_data="set_invite_limit"))
    markup.add(InlineKeyboardButton("⏱ Время на оплату", callback_data="set_payment_time"))

    return markup

def get_trainings_keyboard(
    trainings: Union[List[Tuple[int, str, str, str]], List[Training]], 
    action: str
) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for training in trainings:
        if isinstance(training, Training):
            training_id = training.id
            date_time = training.date_time.strftime('%Y-%m-%d %H:%M')
            training_kind = training.kind
            location = training.location
        else:
            training_id = training[0]
            date_time = training[1]
            training_kind = training[2]
            location = training[3]

        button_text = f"{date_time} | {training_kind} | {location}"

        callback_data = f"{action}_{training_id}"
            
        markup.add(InlineKeyboardButton(button_text, callback_data=callback_data))
    
    return markup

def get_confirm_keyboard() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Подтвердить", callback_data="confirm_clear"))
    markup.add(InlineKeyboardButton("Отмена", callback_data="cancel"))
    return markup
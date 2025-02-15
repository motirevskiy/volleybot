from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Tuple, Union
from datetime import datetime
from new_bot.types import Training

def get_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создает основное меню"""
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("📋 Мои тренировки", callback_data="my_trainings"),
        InlineKeyboardButton("📊 Расписание", callback_data="get_schedule"),
    )
    markup.add(InlineKeyboardButton("🎫 Автозапись", callback_data="auto_signup"))
    markup.add(InlineKeyboardButton("📝 Записаться на тренировку", callback_data="sign_up_training"))
    markup.add(InlineKeyboardButton("👥 Записать друга", callback_data="invite_friend"))
    markup.add(InlineKeyboardButton("Получить права администратора", callback_data="get_admin"))
    markup.add(InlineKeyboardButton("Отписаться от рассылки", callback_data="cancel_message_sign_up"))
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

def get_admin_list_keyboard(admins: List[Tuple[str]]) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    for admin in admins:
        markup.add(InlineKeyboardButton(f"Удалить {admin[0]}", callback_data=f"remadm_{admin[0]}"))
    return markup

def get_confirm_keyboard() -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Подтвердить", callback_data="confirm_clear"))
    markup.add(InlineKeyboardButton("Отмена", callback_data="cancel"))
    return markup

def get_training_keyboard(training_id: int) -> InlineKeyboardMarkup:
    """Создает клавиатуру для тренировки с кнопками записи/отмены"""
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("Записаться", callback_data=f"signup_{training_id}"))
    markup.add(InlineKeyboardButton("Отменить запись", callback_data=f"cancel_{training_id}"))
    return markup

def get_user_trainings_keyboard(trainings: List[Training], admin_username: str) -> InlineKeyboardMarkup:
    markup = InlineKeyboardMarkup()
    
    # Добавляем кнопку для просмотра реквизитов
    markup.add(InlineKeyboardButton(
        "💳 Реквизиты для оплаты",
        callback_data="show_payment_details"
    ))
    
    for training in trainings:
        training_text = (
            f"{training.date_time.strftime('%Y-%m-%d %H:%M')} | "
            f"{training.kind} | {training.location}"
        )
        markup.add(InlineKeyboardButton(training_text, callback_data=f"training_{training.id}"))
    
    return markup 
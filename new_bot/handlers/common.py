from telebot.types import Message
from new_bot.database.admin import AdminDB
from new_bot.utils.keyboards import get_main_menu_keyboard
from new_bot.types import BotType

admin_db = AdminDB()

def register_common_handlers(bot: BotType) -> None:
    @bot.message_handler(commands=['start'])
    def start(message: Message):
        markup = get_main_menu_keyboard()
        bot.reply_to(
            message,
            "Добро пожаловать! Выберите действие:",
            reply_markup=markup
        )
        admin_db.add_user(message.from_user.id, message.from_user.username)

    @bot.message_handler(commands=['chatid'])
    def get_chat_id(message: Message):
        bot.reply_to(message, f"ID этого чата: {message.chat.id}") 
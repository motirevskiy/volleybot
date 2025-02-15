# Пустой файл для обозначения пакета 
from telebot import TeleBot
from new_bot.config import TOKEN as BOT_TOKEN
from new_bot.handlers.admin import register_admin_handlers
from new_bot.handlers.user import register_user_handlers
from new_bot.utils.scheduler import InvitationScheduler

def create_bot():
    bot = TeleBot(BOT_TOKEN)
    
    # Регистрируем обработчики
    register_admin_handlers(bot)
    register_user_handlers(bot)
    
    # Запускаем планировщик проверки приглашений
    scheduler = InvitationScheduler(bot)
    scheduler.start()
    
    return bot 
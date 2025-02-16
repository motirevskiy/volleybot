import telebot
from new_bot.config import TOKEN
from new_bot.handlers import (
    register_admin_handlers,
    register_user_handlers,
    register_common_handlers
)
import threading
import time
from datetime import datetime
from new_bot.utils.scheduler import (
    PaymentScheduler, 
    ReserveScheduler, 
    InvitationScheduler,
    ReminderScheduler
)

def main():
    while True:
        try:
            # Инициализация бота
            bot = telebot.TeleBot(TOKEN)
            
            # Регистрация всех обработчиков
            register_common_handlers(bot)
            register_admin_handlers(bot)
            register_user_handlers(bot)
            
            # Запускаем планировщики
            payment_scheduler = PaymentScheduler(bot)
            reserve_scheduler = ReserveScheduler(bot)
            invitation_scheduler = InvitationScheduler(bot)
            reminder_scheduler = ReminderScheduler(bot)
            
            payment_scheduler.start()
            reserve_scheduler.start()
            invitation_scheduler.start()
            reminder_scheduler.start()
            
            # Запуск бота с настройками переподключения
            print("Бот запущен...")
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            print(f"Произошла ошибка: {e}")
            print("Попытка перезапуска через 5 секунд...")
            time.sleep(5)
            continue

if __name__ == "__main__":
    main() 
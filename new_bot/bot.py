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

def check_and_send_reminders(bot):
    while True:
        try:
            # Перемещаем импорты внутрь функции
            from new_bot.database.admin import AdminDB
            from new_bot.database.trainer import TrainerDB
            
            admin_db = AdminDB()
            admins = admin_db.get_all_admins()
            
            # Для каждого админа проверяем тренировки и отправляем напоминания
            for admin in admins:
                try:
                    trainer_db = TrainerDB(admin[0])
                    trainer_db.send_training_reminders(bot, hours_before=24)  # За 24 часа
                    trainer_db.send_training_reminders(bot, hours_before=1)   # За 1 час
                except Exception as e:
                    print(f"Ошибка при отправке напоминаний для админа {admin[0]}: {e}")
                    continue
                
        except Exception as e:
            print(f"Ошибка при отправке напоминаний: {e}")
            
        # Проверяем каждые 30 минут
        time.sleep(1800)

def main():
    while True:
        try:
            # Инициализация бота
            bot = telebot.TeleBot(TOKEN)
            
            # Регистрация всех обработчиков
            register_common_handlers(bot)
            register_admin_handlers(bot)
            register_user_handlers(bot)
            
            # Запускаем поток для проверки напоминаний
            reminder_thread = threading.Thread(target=check_and_send_reminders, args=(bot,))
            reminder_thread.daemon = True
            reminder_thread.start()
            
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
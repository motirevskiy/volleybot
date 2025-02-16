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
from new_bot.utils.scheduler import PaymentScheduler, ReserveScheduler, InvitationScheduler

def check_and_send_reminders(bot):
    """Проверяет и отправляет напоминания о тренировках"""
    while True:
        try:
            from new_bot.database.admin import AdminDB
            from new_bot.database.trainer import TrainerDB
            from new_bot.database.channel import ChannelDB
            
            admin_db = AdminDB()
            channel_db = ChannelDB()
            admins = admin_db.get_all_admins()
            
            for admin in admins:
                try:
                    admin_username = admin[0]
                    trainer_db = TrainerDB(admin_username)
                    trainings = trainer_db.get_all_trainings()
                    
                    for training in trainings:
                        if training.status != "OPEN":
                            continue
                            
                        time_until = training.date_time - datetime.now()
                        hours_until = time_until.total_seconds() / 3600
                        
                        # Получаем участников
                        participants = trainer_db.fetch_all('''
                            SELECT username 
                            FROM participants 
                            WHERE training_id = ? 
                            AND status = 'ACTIVE'
                        ''', (training.id,))
                        
                        # Получаем информацию о группе
                        group = channel_db.get_channel(training.channel_id)
                        if not group:
                            continue
                        
                        # За 24 часа
                        if 23.9 <= hours_until <= 24.1:
                            for participant in participants:
                                username = participant[0]
                                if user_id := admin_db.get_user_id(username):
                                    notification = (
                                        "⏰ Напоминание о тренировке через 24 часа:\n\n"
                                        f"👥 Группа: {group[1]}\n"
                                        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                                        f"🏋️‍♂️ Тип: {training.kind}\n"
                                        f"📍 Место: {training.location}"
                                    )
                                    try:
                                        bot.send_message(user_id, notification)
                                    except Exception as e:
                                        print(f"Error sending 24h reminder to {username}: {e}")
                        
                        # За 1 час
                        if 0.9 <= hours_until <= 1.1:
                            for participant in participants:
                                username = participant[0]
                                if user_id := admin_db.get_user_id(username):
                                    notification = (
                                        "⏰ Напоминание о тренировке через 1 час:\n\n"
                                        f"👥 Группа: {group[1]}\n"
                                        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                                        f"🏋️‍♂️ Тип: {training.kind}\n"
                                        f"📍 Место: {training.location}"
                                    )
                                    try:
                                        bot.send_message(user_id, notification)
                                    except Exception as e:
                                        print(f"Error sending 1h reminder to {username}: {e}")
                                        
                except Exception as e:
                    print(f"Error processing reminders for admin {admin_username}: {e}")
                    continue
                    
        except Exception as e:
            print(f"Error in reminder checker: {e}")
            
        time.sleep(660)  # Проверяем каждые 8 минут

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
            payment_scheduler.start()
            
            reserve_scheduler = ReserveScheduler(bot)
            reserve_scheduler.start()

            invitation_scheduler = InvitationScheduler(bot)
            invitation_scheduler.start()
            
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
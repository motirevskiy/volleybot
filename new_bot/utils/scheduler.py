import threading
import time
from datetime import datetime
from typing import Dict
from new_bot.database.trainer import TrainerDB
from new_bot.database.admin import AdminDB
from telebot import TeleBot

class InvitationScheduler:
    def __init__(self, bot: TeleBot):
        self.bot = bot
        self.admin_db = AdminDB()
        self.is_running = False
        self.thread = None
        
    def start(self):
        """Запускает планировщик в отдельном потоке"""
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True  # Поток будет завершен вместе с основной программой
            self.thread.start()
            
    def stop(self):
        """Останавливает планировщик"""
        self.is_running = False
        if self.thread:
            self.thread.join()
            
    def _run(self):
        """Основной цикл проверки приглашений"""
        while self.is_running:
            try:
                self._check_expired_invites()
            except Exception as e:
                print(f"Error in invitation scheduler: {e}")
            time.sleep(60)  # Проверяем каждую минуту
            
    def _check_expired_invites(self):
        """Проверяет и обрабатывает просроченные приглашения"""
        # Получаем всех админов
        admins = self.admin_db.get_all_admins()
        
        for admin in admins:
            admin_username = admin[0]
            trainer_db = TrainerDB(admin_username)
            
            # Получаем просроченные приглашения
            expired_invites = trainer_db.fetch_all('''
                SELECT username, training_id 
                FROM invites 
                WHERE status = 'PENDING'
                AND invite_timestamp < datetime('now', '-2 hours')
            ''')
            
            for invite in expired_invites:
                username, training_id = invite
                
                # Отмечаем приглашение как отклоненное
                trainer_db.execute_query('''
                    UPDATE invites 
                    SET status = 'DECLINED' 
                    WHERE username = ? AND training_id = ?
                ''', (username, training_id))
                
                # Отправляем уведомление пользователю
                user_id = self.admin_db.get_user_id(username)
                if user_id:
                    try:
                        training = trainer_db.get_training_details(training_id)
                        message = (
                            "⌛️ Срок действия приглашения истек:\n\n"
                            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                            f"🏋️‍♂️ Тип: {training.type}\n"
                            f"📍 Место: {training.location}"
                        )
                        self.bot.send_message(user_id, message)
                    except Exception as e:
                        print(f"Error sending notification to {username}: {e}") 
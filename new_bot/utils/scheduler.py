import threading
import time
from datetime import datetime, timedelta
from typing import Dict
from new_bot.database.trainer import TrainerDB
from new_bot.database.admin import AdminDB
from new_bot.database.channel import ChannelDB
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

class PaymentScheduler:
    def __init__(self, bot: TeleBot):
        self.bot = bot
        self.admin_db = AdminDB()
        self.channel_db = ChannelDB()
        self.is_running = False
        self.thread = None
        
    def start(self):
        """Запускает планировщик в отдельном потоке"""
        if not self.is_running:
            self.is_running = True
            self.thread = threading.Thread(target=self._run)
            self.thread.daemon = True
            self.thread.start()
            
    def stop(self):
        """Останавливает планировщик"""
        self.is_running = False
        if self.thread:
            self.thread.join()
            
    def _run(self):
        """Основной цикл проверки оплат"""
        while self.is_running:
            try:
                self._check_payments()
            except Exception as e:
                print(f"Error in payment scheduler: {e}")
            time.sleep(60)  # Проверяем каждую минуту
            
    def _check_payments(self):
        """Проверяет оплаты и перемещает неоплативших в резерв"""
        # Получаем всех админов
        admins = self.admin_db.get_all_admins()
        
        for admin in admins:
            admin_username = admin[0]
            payment_time_limit = self.admin_db.get_payment_time_limit(admin_username)
            
            # Пропускаем, если функция отключена
            if payment_time_limit == 0:
                continue
                
            trainer_db = TrainerDB(admin_username)
            trainings = trainer_db.get_all_trainings()
            
            for training in trainings:
                if training.status != "OPEN":
                    continue
                    
                participants = trainer_db.get_participants_by_training_id(training.id)
                for username in participants:
                    # Проверяем время с момента записи
                    signup_time = trainer_db.get_signup_time(username, training.id)
                    if not signup_time:
                        continue
                        
                    time_passed = (datetime.now() - signup_time).total_seconds() / 60
                    if time_passed > payment_time_limit:
                        # Проверяем оплату
                        if trainer_db.get_payment_status(username, training.id) != 2:
                            # Получаем информацию о группе
                            group = self.channel_db.get_channel(training.channel_id)
                            if not group:
                                continue
                                
                            # Перемещаем в резерв
                            trainer_db.remove_participant(username, training.id)
                            position = trainer_db.add_to_reserve(username, training.id)
                            
                            # Уведомляем участника
                            if user_id := self.admin_db.get_user_id(username):
                                notification = (
                                    "⚠️ Вы перемещены в резерв из-за отсутствия оплаты:\n\n"
                                    f"👥 Группа: {group[1]}\n"
                                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                                    f"🏋️‍♂️ Тип: {training.kind}\n"
                                    f"📍 Место: {training.location}\n"
                                    f"📋 Позиция в резерве: {position}"
                                )
                                try:
                                    self.bot.send_message(user_id, notification)
                                except Exception as e:
                                    print(f"Error notifying user {username}: {e}")
                            
                            # Предлагаем место следующему в резерве
                            if next_username := trainer_db.offer_spot_to_next_in_reserve(training.id):
                                if user_id := self.admin_db.get_user_id(next_username):
                                    notification = (
                                        "🎉 Освободилось место на тренировке!\n\n"
                                        f"👥 Группа: {group[1]}\n"
                                        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                                        f"🏋️‍♂️ Тип: {training.kind}\n"
                                        f"📍 Место: {training.location}\n\n"
                                        "У вас есть 2 часа, чтобы подтвердить участие"
                                    )
                                    try:
                                        self.bot.send_message(user_id, notification)
                                    except Exception as e:
                                        print(f"Error notifying reserve user {next_username}: {e}")
                            
                            # Уведомляем админа
                            if admin_id := self.admin_db.get_user_id(admin_username):
                                notification = (
                                    f"ℹ️ Участник @{username} перемещен в резерв из-за отсутствия оплаты:\n\n"
                                    f"👥 Группа: {group[1]}\n"
                                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                                    f"🏋️‍♂️ Тип: {training.kind}"
                                )
                                try:
                                    self.bot.send_message(admin_id, notification)
                                except Exception as e:
                                    print(f"Error notifying admin {admin_username}: {e}")
                            
                            # Обновляем список в форуме
                            if topic_id := trainer_db.get_topic_id(training.id):
                                from new_bot.utils.forum_manager import ForumManager
                                forum_manager = ForumManager(self.bot)
                                participants = trainer_db.get_participants_by_training_id(training.id)
                                forum_manager.update_participants_list(training, participants, topic_id, trainer_db) 
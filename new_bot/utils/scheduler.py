import threading
import time
from datetime import datetime, timedelta
from typing import Dict
from new_bot.database.trainer import TrainerDB
from new_bot.database.admin import AdminDB
from new_bot.database.channel import ChannelDB
from telebot import TeleBot
from new_bot.utils.reserve import offer_spot_to_reserve

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
            time.sleep(10)  # Проверяем каждую минуту
            
    def _check_expired_invites(self):
        """Проверяет и обрабатывает просроченные приглашения"""
        admins = self.admin_db.get_all_admins()
        
        for admin in admins:
            admin_username = admin[0]
            trainer_db = TrainerDB(admin_username)
            
            # Получаем просроченные приглашения (больше 1 часа)
            expired_invites = trainer_db.fetch_all('''
                SELECT username, training_id 
                FROM invites 
                WHERE status = 'PENDING'
                AND invite_timestamp < datetime('now', '+3 hours', '-2 hour')
            ''')
            
            for invite in expired_invites:
                username, training_id = invite
                
                # Отмечаем приглашение как отклоненное
                trainer_db.execute_query('''
                    UPDATE invites 
                    SET status = 'DECLINED' 
                    WHERE username = ? AND training_id = ?
                ''', (username, training_id))

                trainer_db.remove_participant(username, training_id)
                trainer_db.remove_from_reserve(username, training_id)

                # Отправляем уведомление пользователю
                if user_id := self.admin_db.get_user_id(username):
                    training = trainer_db.get_training_details(training_id)
                    if training:
                        notification = (
                            "⌛️ Время на принятие приглашения истекло:\n\n"
                            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                            f"🏋️‍♂️ Тип: {training.kind}\n"
                            f"📍 Место: {training.location}"
                        )
                        try:
                            self.bot.send_message(user_id, notification)
                        except Exception as e:
                            print(f"Error notifying user {username}: {e}")
                            
                        # Обновляем список в форуме
                        if topic_id := trainer_db.get_topic_id(training_id):
                            from new_bot.utils.forum_manager import ForumManager
                            forum_manager = ForumManager(self.bot)
                            participants = trainer_db.get_participants_by_training_id(training_id)
                            forum_manager.update_participants_list(training, participants, topic_id, trainer_db)

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
        admins = self.admin_db.get_all_admins()
        
        for admin in admins:
            admin_username = admin[0]
            payment_time_limit = self.admin_db.get_payment_time_limit(admin_username)
            print(payment_time_limit)
            
            # Пропускаем, если функция отключена
            if payment_time_limit == 0:
                continue
                
            trainer_db = TrainerDB(admin_username)
            trainings = trainer_db.get_all_trainings()
            
            for training in trainings:
                if training.status != "OPEN":
                    continue
                    
                # Получаем только активных участников (не RESERVE_PENDING)
                participants = trainer_db.fetch_all('''
                    SELECT username 
                    FROM participants 
                    WHERE training_id = ? 
                    AND status = 'ACTIVE'
                ''', (training.id,))
                
                for participant in participants:
                    username = participant[0]
                    # Проверяем время с момента записи
                    signup_time = trainer_db.get_signup_time(username, training.id)
                    print(signup_time)
                    if not signup_time:
                        continue
                        
                    time_passed = (datetime.now() - signup_time).total_seconds() / 60
                    print(time_passed)
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
                                    f"📋 Позиция в резерве: {position}\n\n"
                                    f"Время на оплату: {payment_time_limit/60} часов"
                                )
                                try:
                                    self.bot.send_message(user_id, notification)
                                except Exception as e:
                                    print(f"Error notifying user {username}: {e}")
                            
                            # Предлагаем место следующему в резерве
                            offer_spot_to_reserve(training.id, admin_username, self.bot)
                            
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

class ReserveScheduler:
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
        """Основной цикл проверки резерва"""
        while self.is_running:
            try:
                self._check_expired_offers()
            except Exception as e:
                print(f"Error in reserve scheduler: {e}")
            time.sleep(10)  # Проверяем каждые 10 секунд
            
    def _check_expired_offers(self):
        """Проверяет и обрабатывает просроченные предложения из резерва"""
        admins = self.admin_db.get_all_admins()
        
        for admin in admins:
            admin_username = admin[0]
            trainer_db = TrainerDB(admin_username)
            
            # Получаем просроченные предложения (больше 2 часов)
            expired_offers = trainer_db.fetch_all('''
                SELECT username, training_id, signup_time 
                FROM participants 
                WHERE status = 'RESERVE_PENDING'
                AND signup_time < datetime('now', '+3 hours', '-2 hours')
            ''')
            
            for offer in expired_offers:
                username, training_id, signup_time = offer
                print(f"Processing expired offer: user={username}, training={training_id}, signup_time={signup_time}")
                
                # Удаляем из основного списка
                trainer_db.execute_query(
                    "DELETE FROM participants WHERE username = ? AND training_id = ? AND status = 'RESERVE_PENDING'",
                    (username, training_id)
                )
                
                # Добавляем в конец резерва с новым статусом WAITING
                position = trainer_db.add_to_reserve(username, training_id)
                print(f"Added {username} back to reserve at position {position}")
                
                # Сбрасываем статус в резерве на WAITING
                trainer_db.execute_query('''
                    UPDATE reserve 
                    SET status = 'WAITING' 
                    WHERE username = ? AND training_id = ?
                ''', (username, training_id))
                
                # Предлагаем место следующему
                offer_spot_to_reserve(training_id, admin_username, self.bot)
                
                # Уведомляем пользователя
                if user_id := self.admin_db.get_user_id(username):
                    training = trainer_db.get_training_details(training_id)
                    if training:
                        notification = (
                            "⌛️ Время на принятие места истекло:\n\n"
                            f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                            f"🏋️‍♂️ Тип: {training.kind}\n"
                            f"📍 Место: {training.location}\n\n"
                            f"Вы перемещены на позицию {position} в списке резерва"
                        )
                        try:
                            self.bot.send_message(user_id, notification)
                            print(f"Sent notification to {username}")
                        except Exception as e:
                            print(f"Error notifying user {username}: {e}") 

class ReminderScheduler:
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
        """Основной цикл проверки напоминаний"""
        while self.is_running:
            try:
                self._check_and_send_reminders()
            except Exception as e:
                print(f"Error in reminder scheduler: {e}")
            time.sleep(660)  # Проверяем каждые 8 минут
            
    def _check_and_send_reminders(self):
        """Проверяет и отправляет напоминания о тренировках"""
        admins = self.admin_db.get_all_admins()
        
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
                    group = self.channel_db.get_channel(training.channel_id)
                    if not group:
                        continue
                    
                    # За 24 часа
                    if 23.9 <= hours_until <= 24.1:
                        for participant in participants:
                            username = participant[0]
                            if user_id := self.admin_db.get_user_id(username):
                                notification = (
                                    "⏰ Напоминание о тренировке через 24 часа:\n\n"
                                    f"👥 Группа: {group[1]}\n"
                                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                                    f"🏋️‍♂️ Тип: {training.kind}\n"
                                    f"📍 Место: {training.location}"
                                )
                                try:
                                    self.bot.send_message(user_id, notification)
                                except Exception as e:
                                    print(f"Error sending 24h reminder to {username}: {e}")
                    
                    # За 1 час
                    if 0.9 <= hours_until <= 1.1:
                        for participant in participants:
                            username = participant[0]
                            if user_id := self.admin_db.get_user_id(username):
                                notification = (
                                    "⏰ Напоминание о тренировке через 1 час:\n\n"
                                    f"👥 Группа: {group[1]}\n"
                                    f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
                                    f"🏋️‍♂️ Тип: {training.kind}\n"
                                    f"📍 Место: {training.location}"
                                )
                                try:
                                    self.bot.send_message(user_id, notification)
                                except Exception as e:
                                    print(f"Error sending 1h reminder to {username}: {e}")
                                    
            except Exception as e:
                print(f"Error processing reminders for admin {admin_username}: {e}")
                continue 
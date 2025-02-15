import os
from new_bot.database.base import BaseDB
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from new_bot.types import Training, User

class TrainerDB(BaseDB):
    def __init__(self, admin_username: str):
        db_path = f'trainer_{admin_username}.db'
        super().__init__(db_path)

    def _initialize_db(self):
        # Создаем основные таблицы
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS schedule (
                training_id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_time TEXT,
                duration INTEGER,
                kind TEXT,
                location TEXT,
                status TEXT,
                max_participants INTEGER DEFAULT 10,
                price INTEGER DEFAULT 0,
                topic_id INTEGER DEFAULT NULL
            )
        ''')
        
        # Проверяем существующие колонки
        columns = self.fetch_all("PRAGMA table_info(schedule)")
        column_names = [column[1] for column in columns]
        
        # Добавляем колонку topic_id, если её нет
        if 'topic_id' not in column_names:
            self.execute_query('ALTER TABLE schedule ADD COLUMN topic_id INTEGER DEFAULT NULL')
            
        # Добавляем колонку price, если её нет
        if 'price' not in column_names:
            self.execute_query('ALTER TABLE schedule ADD COLUMN price INTEGER DEFAULT 0')

        self.execute_query('''
            CREATE TABLE IF NOT EXISTS participants (
                username TEXT,
                training_id INTEGER,
                status TEXT DEFAULT 'ACTIVE',
                paid INTEGER DEFAULT 0,  /* 0 - не оплачено, 1 - ожидает подтверждения, 2 - подтверждено */
                FOREIGN KEY (training_id) REFERENCES schedule(training_id)
            )
        ''')
        # Добавим таблицу для статистики
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS statistics (
                username TEXT,
                training_id INTEGER,
                action TEXT,  -- 'signup' или 'cancel'
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(training_id) REFERENCES schedule(training_id)
            )
        ''')

        # Добавляем таблицу для резерва
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS reserve (
                username TEXT,
                training_id INTEGER,
                position INTEGER,
                status TEXT DEFAULT 'WAITING',
                offer_timestamp DATETIME,  -- Время, когда было сделано предложение
                FOREIGN KEY(training_id) REFERENCES schedule(training_id)
            )
        ''')

        # Добавляем таблицу для приглашений
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS invites (
                username TEXT,
                invited_by TEXT,
                training_id INTEGER,
                status TEXT DEFAULT 'PENDING',
                invite_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(training_id) REFERENCES schedule(training_id)
            )
        ''')

        # Таблица для хранения баланса автозаписей
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS auto_signups_balance (
                username TEXT PRIMARY KEY,
                balance INTEGER DEFAULT 1
            )
        ''')
        
        # Таблица для хранения запросов на автозапись
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS auto_signup_requests (
                username TEXT,
                training_id INTEGER,
                request_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (username, training_id),
                FOREIGN KEY (training_id) REFERENCES schedule(training_id) ON DELETE CASCADE
            )
        ''')

    def add_training(self, date_time: str, duration: int, kind: str, location: str, max_participants: int, status: str, price: int) -> int:
        """
        Добавляет новую тренировку.
        
        Args:
            date_time: дата и время тренировки
            duration: длительность в минутах
            kind: тип тренировки
            location: место проведения
            max_participants: максимальное количество участников
            status: статус тренировки (OPEN/CLOSE), по умолчанию CLOSE
            
        Returns:
            int: ID созданной тренировки
        """
        try:
            self.execute_query('''
                INSERT INTO schedule 
                (date_time, duration, kind, location, max_participants, status, price)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (date_time, duration, kind, location, max_participants, status, price))
            
            return self.cursor.lastrowid
        except Exception as e:
            print(f"Error adding training: {e}")
            return 0

    def update_training(self, training_id: int, date_time: str, duration: int, 
                       kind: str, location: str, max_participants: int, 
                       price: int, status: str) -> None:
        """Обновляет существующую тренировку"""
        self.execute_query('''
            UPDATE schedule
            SET date_time = ?, duration = ?, kind = ?, location = ?, 
                max_participants = ?, price = ?, status = ?
            WHERE training_id = ?
        ''', (date_time, duration, kind, location, max_participants, price, status, training_id))

    def delete_training(self, training_id: int) -> bool:
        """Удаляет тренировку и все связанные записи"""
        if self.fetch_all("SELECT 1 FROM schedule WHERE training_id = ?", (training_id,)) is None:
            return False
        
        # Удаляем записи участников
        self.execute_query(
            "DELETE FROM participants WHERE training_id = ?", 
            (training_id,)
        )
        
        # Удаляем запросы на автозапись (без возврата баланса)
        self.execute_query(
            "DELETE FROM auto_signup_requests WHERE training_id = ?",
            (training_id,)
        )
        
        # Удаляем саму тренировку
        self.execute_query(
            "DELETE FROM schedule WHERE training_id = ?", 
            (training_id,)
        )
        return True

    def add_participant(self, username: str, training_id: int) -> bool:
        """Добавляет участника в тренировку"""
        try:
            
            # Проверяем существование тренировки
            training = self.get_training_details(training_id)
            if not training:
                return False
            
            
            # Проверяем количество текущих участников
            current_participants = self.get_participants_by_training_id(training_id)
            
            if len(current_participants) >= training.max_participants:
                return False
            
            # Проверяем, не записан ли уже пользователь
            if self.is_participant(username, training_id):
                return False
            
            # Добавляем участника
            self.execute_query('''
                INSERT INTO participants (username, training_id)
                VALUES (?, ?)
            ''', (username, training_id))
            
            # Проверяем успешность добавления
            if self.is_participant(username, training_id):
                return True
            else:
                return False
            
        except Exception as e:
            import traceback
            return False

    def remove_participant(self, username: str, training_id: int) -> bool:
        """Удаляет участника из тренировки"""
        
        try:
            self.execute_query(
                "DELETE FROM participants WHERE username = ? AND training_id = ?",
                (username, training_id)
            )
            return True
        except Exception as e:
            print(f"Ошибка удаления участника: {e}")
            return False

    def get_participants_by_training_id(self, training_id: int) -> List[str]:
        """Получает список участников тренировки"""
        result = self.fetch_all('''
            SELECT username, status FROM participants
            WHERE training_id = ?
            ORDER BY rowid
        ''', (training_id,))
        # Правильно извлекаем username из Row объекта
        participants = []
        for row in result:
            participants.append(dict(row)['username'])
        return participants

    def get_trainings_for_user(self, username: str) -> List[Training]:
        rows = self.fetch_all('''
            SELECT s.training_id, s.date_time, s.duration, s.kind, s.location, s.status, s.max_participants, s.price
            FROM schedule s
            JOIN participants p ON s.training_id = p.training_id
            WHERE p.username = ?
        ''', (username,))
        
        return [
            Training(
                id=row[0],
                date_time=datetime.strptime(row[1], '%Y-%m-%d %H:%M'),
                duration=row[2],
                kind=row[3],
                location=row[4],
                status=row[5],
                max_participants=row[6],
                price=row[7]
            ) for row in rows
        ]

    def get_training_details(self, training_id: int) -> Optional[Training]:
        """Получает детали тренировки по ID"""
        result = self.fetch_one('''
            SELECT training_id, date_time, duration, 
            kind, location, max_participants, status, price
            FROM schedule WHERE training_id = ?
        ''', (training_id,))
        
        if result:
            return Training(
                id=result[0],
                date_time=datetime.strptime(result[1], '%Y-%m-%d %H:%M'),
                duration=result[2],
                kind=result[3],
                location=result[4],
                max_participants=result[5],
                status=result[6],
                price=result[7]
            )
        return None
    
    def get_training_ids(self) -> List[Tuple[int]]:
        """Получает список ID всех тренировок"""
        print("Вызван метод get_training_ids")  # Отладка
        result = self.fetch_all("SELECT training_id FROM schedule")
        print(f"Найдено тренировок: {len(result)}")  # Отладка
        return result
    
    def set_training_open(self, training_id: int) -> bool:
        """Открывает запись на тренировку"""
        try:
            self.execute_query(
                "UPDATE schedule SET status = 'OPEN' WHERE training_id = ?",
                (training_id,)
            )
            return True
        except Exception as e:
            print(f"Error setting training open: {e}")
            return False

    def get_closed_trainings(self) -> List[Training]:
        """
        Получает список закрытых тренировок.
        
        Returns:
            List[Training]: Список тренировок
        """
        rows = self.fetch_all(
            """
            SELECT training_id, date_time, duration, kind, location, max_participants, status, price
            FROM schedule 
            WHERE status != 'OPEN'
            """
        )
        return [
            Training(
                id=row[0],
                date_time=datetime.strptime(row[1], '%Y-%m-%d %H:%M'),
                duration=row[2],
                kind=row[3],
                location=row[4],
                max_participants=row[5],
                status=row[6],
                price=row[7]
            ) for row in rows
        ]

    def notify_participants_about_deletion(self, bot: 'BotType', training_id: int) -> None:
        """
        Уведомляет всех участников и резерв об отмене тренировки.
        
        Args:
            bot: Экземпляр бота для отправки сообщений
            training_id: ID тренировки
        """
        # Получаем детали тренировки перед удалением
        training = self.get_training_details(training_id)
        if not training:
            return
            
        # Получаем список участников и резерва
        participants = self.get_participants_by_training_id(training_id)
        reserve_list = self.get_reserve_list(training_id)
        
        # Формируем сообщение об отмене
        cancel_message = (
            f"❌ Тренировка была отменена:\n"
            f"Дата: {training.date_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"Тип: {training.kind}\n"
            f"Место: {training.location}"
        )
        
        # Получаем user_id для каждого участника из таблицы users
        from new_bot.database.admin import AdminDB
        admin_db = AdminDB()
        
        # Уведомляем основных участников
        for username in participants:
            user = admin_db.fetch_one(
                "SELECT user_id FROM users WHERE username = ?",
                (username,)
            )
            if user:
                try:
                    bot.send_message(user[0], cancel_message)
                except Exception as e:
                    print(f"Ошибка отправки уведомления пользователю {username}: {e}")
        
        # Уведомляем участников из резерва
        reserve_message = (
            f"❌ Тренировка, в резерве которой вы находились, была отменена:\n"
            f"Дата: {training.date_time.strftime('%Y-%m-%d %H:%M')}\n"
            f"Тип: {training.kind}\n"
            f"Место: {training.location}"
        )
        
        for username, position, status in reserve_list:
            user = admin_db.fetch_one(
                "SELECT user_id FROM users WHERE username = ?",
                (username,)
            )
            if user:
                try:
                    bot.send_message(user[0], reserve_message)
                except Exception as e:
                    print(f"Ошибка отправки уведомления пользователю {username}: {e}")

    def get_user_statistics(self, username: str) -> dict:
        """Получает статистику пользователя"""
        stats = {
            'total_signups': 0,
            'total_cancellations': 0,
            'recent_activities': []
        }
        
        result = self.fetch_all('''
            SELECT action, COUNT(*) 
            FROM statistics 
            WHERE username = ?
            GROUP BY action
        ''', (username,))
        
        for action, count in result:
            if action == 'signup':
                stats['total_signups'] = count
            elif action == 'cancel':
                stats['total_cancellations'] = count
                
        # Получаем последние 5 действий
        recent = self.fetch_all('''
            SELECT s.action, s.timestamp, sch.kind, sch.date_time
            FROM statistics s
            JOIN schedule sch ON s.training_id = sch.training_id
            WHERE s.username = ?
            ORDER BY s.timestamp DESC
            LIMIT 5
        ''', (username,))
        
        stats['recent_activities'] = recent
        return stats 

    def send_training_reminders(self, bot: 'BotType', hours_before: int = 24) -> None:
        """
        Отправляет напоминания о предстоящих тренировках.
        
        Args:
            bot: Экземпляр бота для отправки сообщений
            hours_before: За сколько часов до тренировки отправлять напоминание
        """
        # Получаем тренировки, которые начнутся через hours_before часов
        target_time = datetime.now() + timedelta(hours=hours_before)
        target_time_str = target_time.strftime('%Y-%m-%d %H:%M')
        
        upcoming_trainings = self.fetch_all('''
            SELECT training_id, date_time, duration, kind, location, status, max_participants
            FROM schedule
            WHERE date_time = ?
            AND status = 'OPEN'
        ''', (target_time_str,))

        # Перемещаем импорт внутрь функции
        from new_bot.utils.notifications import NotificationManager
        notification_manager = NotificationManager(bot)
        
        for training_data in upcoming_trainings:
            training = Training.from_db_row(training_data[1:])
            training.id = training_data[0]
            participants = self.get_participants_by_training_id(training.id)
            
            if participants:
                notification_manager.send_reminder(training, participants, hours_before) 

    def remove_all_participants(self, training_id: int) -> None:
        """Удаляет всех участников тренировки"""
        self.execute_query(
            "DELETE FROM participants WHERE training_id = ?", 
            (training_id,)
        ) 

    def update_topic_id(self, training_id: int, topic_id: int) -> None:
        """Обновляет ID темы для тренировки"""
        self.execute_query(
            "UPDATE schedule SET topic_id = ? WHERE training_id = ?",
            (topic_id, training_id)
        )

    def get_topic_id(self, training_id: int) -> Optional[int]:
        """Получает ID темы для тренировки"""
        result = self.fetch_one(
            "SELECT topic_id FROM schedule WHERE training_id = ?",
            (training_id,)
        )
        return result[0] if result else None 

    def add_to_reserve(self, username: str, training_id: int) -> int:
        """Добавляет участника в резерв и возвращает его позицию"""
        
        # Получаем максимальную позицию в резерве
        max_pos = self.fetch_one('''
            SELECT MAX(position) FROM reserve WHERE training_id = ?
        ''', (training_id,))
        
        position = 1 if not max_pos[0] else max_pos[0] + 1
        
        self.execute_query('''
            INSERT INTO reserve (username, training_id, position)
            VALUES (?, ?, ?)
        ''', (username, training_id, position))
        
        return position

    def get_reserve_list(self, training_id: int) -> List[Tuple[str, int, str]]:
        """Получает список резерва с позициями и статусами"""
        return self.fetch_all('''
            SELECT username, position, status 
            FROM reserve 
            WHERE training_id = ? 
            ORDER BY position
        ''', (training_id,))

    def remove_from_reserve(self, username: str, training_id: int) -> None:
        """Удаляет участника из резерва"""
        position = self.fetch_one('''
            SELECT position FROM reserve 
            WHERE username = ? AND training_id = ?
        ''', (username, training_id,))
        
        if position:
            # Удаляем участника
            self.execute_query('''
                DELETE FROM reserve 
                WHERE username = ? AND training_id = ?
            ''', (username, training_id,))
            
            # Сдвигаем позиции оставшихся участников
            self.execute_query('''
                UPDATE reserve 
                SET position = position - 1 
                WHERE training_id = ? AND position > ?
            ''', (training_id, position[0]))

    def offer_spot_to_next_in_reserve(self, training_id: int) -> Optional[str]:
        """Предлагает место следующему участнику в резерве"""
        self.debug_participant_info(None, training_id)  # Перед изменениями
        
        next_in_reserve = self.fetch_one('''
            SELECT username FROM reserve 
            WHERE training_id = ? AND status = 'WAITING'
            ORDER BY position ASC
            LIMIT 1
        ''', (training_id,))
        
        
        if next_in_reserve:
            username = next_in_reserve[0]
            
            try:
                # Добавляем участника в основной список со статусом PENDING
                self.execute_query('''
                    INSERT INTO participants (username, training_id, status)
                    VALUES (?, ?, 'PENDING')
                ''', (username, training_id))
                
                self.debug_participant_info(username, training_id)  # После добавления
                
                # Проверяем, что добавление прошло успешно
                added = self.fetch_one('''
                    SELECT status FROM participants
                    WHERE username = ? AND training_id = ? AND status = 'PENDING'
                ''', (username, training_id))
                
                if added:
                    self.remove_from_reserve(username, training_id)
                    
                    self.schedule_pending_cleanup(username, training_id)
                    
                    return username
                else:
                    print("[ERROR] Failed to add participant with PENDING status")
                    return None
            except Exception as e:
                print(f"[ERROR] Error in offer_spot_to_next_in_reserve: {e}")
                return None
        return None

    def schedule_pending_cleanup(self, username: str, training_id: int) -> None:
        """Планирует очистку через 2 часа"""
        from threading import Timer
        
        def cleanup():
            # Проверяем статус участника
            status = self.fetch_one('''
                SELECT status FROM participants
                WHERE username = ? AND training_id = ?
            ''', (username, training_id))
            
            if status and status[0] == 'PENDING':
                # Удаляем из списка и предлагаем место следующему
                self.execute_query('''
                    DELETE FROM participants
                    WHERE username = ? AND training_id = ? AND status = 'PENDING'
                ''', (username, training_id))
                
                # Предлагаем место следующему в резерве
                self.offer_spot_to_next_in_reserve(training_id)
        
        Timer(7200, cleanup).start()

    def accept_reserve_spot(self, username: str, training_id: int) -> bool:
        """Принимает приглашение, убирая статус PENDING"""
        self.debug_participant_info(username, training_id)  # Перед изменениями
        
        try:
            self.execute_query('''
                UPDATE participants 
                SET status = 'ACTIVE'
                WHERE username = ? AND training_id = ? AND status = 'PENDING'
            ''', (username, training_id))
            
            self.debug_participant_info(username, training_id)  # После изменений
            return True
        except Exception as e:
            print(f"[ERROR] Error in accept_reserve_spot: {e}")
            return False

    def decline_reserve_spot(self, username: str, training_id: int) -> bool:
        """Отклоняет приглашение"""
        try:
            # Удаляем из списка
            self.execute_query('''
                DELETE FROM participants
                WHERE username = ? AND training_id = ? AND status = 'PENDING'
            ''', (username, training_id))
            
            # Предлагаем место следующему
            self.offer_spot_to_next_in_reserve(training_id)
            return True
        except Exception as e:
            print(f"Error in decline_reserve_spot: {e}")
            return False

    def is_spot_available(self, training_id: int) -> bool:
        """Проверяет, есть ли свободные места на тренировке"""
        # Получаем максимальное количество участников
        max_participants = self.fetch_one('''
            SELECT max_participants FROM schedule WHERE training_id = ?
        ''', (training_id,))[0]
        
        # Получаем текущее количество участников (включая PENDING)
        current_participants = self.fetch_one('''
            SELECT COUNT(*) FROM participants 
            WHERE training_id = ? AND status IN ('ACTIVE', 'PENDING')
        ''', (training_id,))[0]
        
        return current_participants < max_participants

    def cancel_reserve(self, username: str, training_id: int) -> bool:
        """Отменяет запись в резерве"""
        position = self.fetch_one('''
            SELECT position FROM reserve 
            WHERE username = ? AND training_id = ?
        ''', (username, training_id))
        
        if not position:
            return False
            
        self.remove_from_reserve(username, training_id)
        return True 

    def swap_participant_with_reserve(self, participant: str, reserve: str, training_id: int) -> bool:
        """Меняет местами участника из основного списка с участником из резерва"""
        # Проверяем, что оба пользователя существуют в нужных списках
        participant_exists = self.fetch_one('''
            SELECT 1 FROM participants 
            WHERE username = ? AND training_id = ?
        ''', (participant, training_id))
        
        reserve_exists = self.fetch_one('''
            SELECT 1 FROM reserve 
            WHERE username = ? AND training_id = ? AND status = 'WAITING'
        ''', (reserve, training_id))
        
        if not (participant_exists and reserve_exists):
            return False
            
        try:
            # Начинаем транзакцию
            self.cursor.execute("BEGIN")
            
            # Удаляем участника из основного списка
            self.cursor.execute(
                "DELETE FROM participants WHERE username = ? AND training_id = ?",
                (participant, training_id)
            )
            
            # Получаем и сохраняем позицию в резерве
            self.cursor.execute(
                "SELECT position FROM reserve WHERE username = ? AND training_id = ?",
                (reserve, training_id)
            )
            reserve_position = self.cursor.fetchone()[0]
            
            # Удаляем участника из резерва
            self.cursor.execute(
                "DELETE FROM reserve WHERE username = ? AND training_id = ?",
                (reserve, training_id)
            )
            
            # Сдвигаем позиции оставшихся участников в резерве
            self.cursor.execute('''
                UPDATE reserve 
                SET position = position - 1 
                WHERE training_id = ? AND position > ?
            ''', (training_id, reserve_position))
            
            # Добавляем участника из резерва в основной список
            self.cursor.execute(
                "INSERT INTO participants (username, training_id) VALUES (?, ?)",
                (reserve, training_id)
            )
            
            # Добавляем бывшего участника в резерв
            max_pos = self.cursor.execute(
                "SELECT MAX(position) FROM reserve WHERE training_id = ?",
                (training_id,)
            ).fetchone()[0]
            
            new_position = 1 if not max_pos else max_pos + 1
            
            self.cursor.execute('''
                INSERT INTO reserve (username, training_id, position, status)
                VALUES (?, ?, ?, 'WAITING')
            ''', (participant, training_id, new_position))
            
            # Завершаем транзакцию
            self.connection.commit()
            return True
            
        except Exception as e:
            self.connection.rollback()
            return False 

    def set_payment_status(self, username: str, training_id: int, status: int):
        """Устанавливает статус оплаты"""
        self.execute_query(
            "UPDATE participants SET paid = ? WHERE username = ? AND training_id = ?",
            (status, username, training_id)
        )

    def get_payment_status(self, username: str, training_id: int) -> int:
        """Получает статус оплаты"""
        result = self.fetch_one(
            "SELECT paid FROM participants WHERE username = ? AND training_id = ?",
            (username, training_id)
        )
        return result[0] if result else 0 

    def is_participant(self, username: str, training_id: int) -> bool:
        """Проверяет, является ли пользователь участником тренировки"""
        result = self.fetch_one('''
            SELECT 1 FROM participants 
            WHERE username = ? AND training_id = ?
        ''', (username, training_id))
        return bool(result) 

    def add_invite(self, username: str, invited_by: str, training_id: int) -> bool:
        """Добавляет приглашение"""
        try:
            self.execute_query('''
                INSERT INTO invites (username, invited_by, training_id)
                VALUES (?, ?, ?)
            ''', (username, invited_by, training_id))
            return True
        except Exception as e:
            print(f"Ошибка добавления приглашения: {e}")
            return False

    def get_user_invites_count(self, username: str, training_id: int) -> int:
        """Возвращает количество активных приглашений пользователя на конкретную тренировку"""
        result = self.fetch_one('''
            SELECT COUNT(*) FROM invites 
            WHERE invited_by = ? 
            AND training_id = ?
            AND status = 'PENDING'
            AND invite_timestamp > datetime('now', '-1 hour')
        ''', (username, training_id))
        return result[0] if result else 0

    def cleanup_old_invites(self):
        """Очищает старые приглашения"""
        self.execute_query('''
            DELETE FROM invites 
            WHERE status = 'PENDING' 
            AND invite_timestamp < datetime('now', '-24 hours')
        ''') 

    def get_invite_status(self, username: str, training_id: int) -> Optional[Tuple[str]]:
        """Получает статус приглашения"""
        return self.fetch_one('''
            SELECT status FROM invites 
            WHERE username = ? AND training_id = ?
            ORDER BY invite_timestamp DESC
            LIMIT 1
        ''', (username, training_id))

    def remove_invite(self, username: str, training_id: int) -> None:
        """Удаляет приглашение"""
        self.execute_query('''
            DELETE FROM invites 
            WHERE username = ? AND training_id = ?
        ''', (username, training_id)) 

    def set_topic_id(self, training_id: int, topic_id: int) -> None:
        """Устанавливает ID темы для тренировки"""
        self.execute_query(
            "UPDATE schedule SET topic_id = ? WHERE training_id = ?",
            (topic_id, training_id)
        ) 

    def set_training_closed(self, training_id: int) -> None:
        """Закрывает запись на тренировку и очищает список участников"""
        # Получаем список участников до очистки
        participants = self.get_participants_by_training_id(training_id)
        
        # Очищаем список участников
        self.execute_query(
            "DELETE FROM participants WHERE training_id = ?",
            (training_id,)
        )
        
        # Очищаем резервный список
        self.execute_query(
            "DELETE FROM reserve WHERE training_id = ?",
            (training_id,)
        )
        
        # Очищаем запросы на автозапись (без возврата баланса)
        self.execute_query(
            "DELETE FROM auto_signup_requests WHERE training_id = ?",
            (training_id,)
        )
        
        # Закрываем запись
        self.execute_query(
            "UPDATE schedule SET status = 'CLOSED' WHERE training_id = ?",
            (training_id,)
        ) 

    def get_participant_status(self, username: str, training_id: int) -> str:
        """Получает статус участника"""
        result = self.fetch_one('''
            SELECT status FROM participants
            WHERE username = ? AND training_id = ?
        ''', (username, training_id))
        # Правильно извлекаем статус из Row объекта
        if result:
            return dict(result)['status']
        return "ACTIVE" 

    def debug_participant_info(self, username: str, training_id: int) -> None:
        """Отладочный метод для проверки данных участника"""
        print("\n=== DEBUG PARTICIPANT INFO ===")
        
        # Проверяем запись в таблице participants
        participant = self.fetch_all('''
            SELECT username, training_id, status, rowid
            FROM participants
            WHERE username = ? AND training_id = ?
        ''', (username, training_id))
        print(f"Participant record: {[dict(row) for row in participant]}")
        
        # Проверяем все записи для этой тренировки
        all_participants = self.fetch_all('''
            SELECT username, training_id, status, rowid
            FROM participants
            WHERE training_id = ?
            ORDER BY rowid
        ''', (training_id,))
        print(f"All participants: {[dict(row) for row in all_participants]}")
        
        # Проверяем резерв
        reserve = self.fetch_all('''
            SELECT username, training_id, position, status
            FROM reserve
            WHERE training_id = ?
            ORDER BY position
        ''', (training_id,))
        print(f"Reserve list: {[dict(row) for row in reserve]}")
        print("===========================\n") 

    def get_auto_signups_balance(self, username: str) -> int:
        """Получает баланс автозаписей пользователя"""
        result = self.fetch_one('''
            SELECT balance FROM auto_signups_balance 
            WHERE username = ?
        ''', (username,))
        
        if not result:
            # Если записи нет, создаем с начальным балансом 1
            self.execute_query('''
                INSERT INTO auto_signups_balance (username, balance)
                VALUES (?, 1)
            ''', (username,))
            return 1
        
        return dict(result)['balance']

    def add_auto_signups(self, username: str, amount: int) -> bool:
        """Добавляет автозаписи пользователю"""
        try:
            current_balance = self.get_auto_signups_balance(username)
            self.execute_query('''
                UPDATE auto_signups_balance 
                SET balance = ? 
                WHERE username = ?
            ''', (current_balance + amount, username))
            return True
        except Exception as e:
            print(f"Error adding auto signups: {e}")
            return False

    def decrease_auto_signups(self, username: str) -> bool:
        """Уменьшает количество автозаписей пользователя на 1"""
        try:
            current_balance = self.get_auto_signups_balance(username)
            if current_balance <= 0:
                return False
            
            self.execute_query('''
                UPDATE auto_signups_balance 
                SET balance = ? 
                WHERE username = ?
            ''', (current_balance - 1, username))
            return True
        except Exception as e:
            print(f"Error decreasing auto signups: {e}")
            return False

    def get_available_auto_signup_slots(self, training_id: int) -> int:
        """Возвращает количество доступных слотов для автозаписи"""
        training = self.get_training_details(training_id)
        if not training:
            return 0
        
        max_auto_slots = training.max_participants // 2
        
        # Получаем текущее количество автозаписей
        current_auto_signups = self.fetch_one('''
            SELECT COUNT(*) as count 
            FROM auto_signup_requests 
            WHERE training_id = ?
        ''', (training_id,))
        
        current_count = dict(current_auto_signups)['count']
        return max_auto_slots - current_count

    def add_auto_signup_request(self, username: str, training_id: int) -> bool:
        """Добавляет запрос на автозапись"""
        try:
            # Проверяем баланс
            if self.get_auto_signups_balance(username) <= 0:
                return False
            
            # Проверяем доступные слоты
            if self.get_available_auto_signup_slots(training_id) <= 0:
                return False
            
            self.execute_query('''
                INSERT INTO auto_signup_requests (username, training_id)
                VALUES (?, ?)
            ''', (username, training_id))
            return True
        except Exception as e:
            print(f"Error adding auto signup request: {e}")
            return False

    def remove_auto_signup_request(self, username: str, training_id: int) -> bool:
        """Удаляет запрос на автозапись"""
        try:
            self.execute_query('''
                DELETE FROM auto_signup_requests 
                WHERE username = ? AND training_id = ?
            ''', (username, training_id))
            return True
        except Exception as e:
            print(f"Error removing auto signup request: {e}")
            return False

    def get_auto_signup_requests(self, training_id: int) -> List[str]:
        """Получает список пользователей, запросивших автозапись на тренировку"""
        result = self.fetch_all('''
            SELECT username 
            FROM auto_signup_requests 
            WHERE training_id = ?
            ORDER BY request_timestamp
        ''', (training_id,))
        
        return [dict(row)['username'] for row in result]

    def get_user_auto_signup_requests(self, username: str) -> List[Training]:
        """Получает список тренировок, на которые пользователь запросил автозапись"""
        result = self.fetch_all('''
            SELECT s.training_id as id, s.date_time, s.duration, s.kind, 
                   s.location, s.status, s.max_participants, s.price
            FROM schedule s
            JOIN auto_signup_requests asr ON s.training_id = asr.training_id
            WHERE asr.username = ?
        ''', (username,))
        
        trainings = []
        for row in result:
            row_dict = dict(row)
            # Преобразуем строку в datetime
            row_dict['date_time'] = datetime.strptime(row_dict['date_time'], '%Y-%m-%d %H:%M')
            trainings.append(Training(**row_dict))
        
        return trainings 

    def has_auto_signup_request(self, username: str, training_id: int) -> bool:
        """Проверяет, есть ли уже запрос на автозапись от пользователя"""
        result = self.fetch_one('''
            SELECT 1 FROM auto_signup_requests 
            WHERE username = ? AND training_id = ?
        ''', (username, training_id))
        return bool(result) 
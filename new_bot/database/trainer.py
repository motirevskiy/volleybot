import os
from new_bot.database.base import BaseDB
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
from new_bot.types import Training

class TrainerDB(BaseDB):
    def __init__(self, admin_username: str):
        db_path = f'trainer_{admin_username}.db'
        super().__init__(db_path)

    def _initialize_db(self):
        # Создаем основные таблицы
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS schedule (
                training_id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id INTEGER NOT NULL,
                date_time TEXT,
                duration INTEGER,
                kind TEXT,
                location TEXT,
                status TEXT,
                max_participants INTEGER DEFAULT 10,
                price INTEGER DEFAULT 0,
                topic_id INTEGER DEFAULT NULL,
                FOREIGN KEY (channel_id) REFERENCES channels(channel_id)
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
                paid INTEGER DEFAULT 0,
                signup_time TIMESTAMP,
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

        # Проверяем существующие колонки в participants
        columns = self.fetch_all("PRAGMA table_info(participants)")
        column_names = [column[1] for column in columns]
        
        if 'signup_time' not in column_names:
            # Создаем новую таблицу с нужной структурой
            self.execute_query('''
                CREATE TABLE IF NOT EXISTS participants_new (
                    username TEXT,
                    training_id INTEGER,
                    status TEXT DEFAULT 'ACTIVE',
                    paid INTEGER DEFAULT 0,
                    signup_time TIMESTAMP,
                    FOREIGN KEY (training_id) REFERENCES schedule(training_id)
                )
            ''')
            
            # Копируем данные из старой таблицы
            self.execute_query('''
                INSERT INTO participants_new (username, training_id, status, paid)
                SELECT username, training_id, status, paid FROM participants
            ''')
            
            # Обновляем время записи для существующих записей
            self.execute_query('''
                UPDATE participants_new 
                SET signup_time = datetime('now') 
                WHERE signup_time IS NULL
            ''')
            
            # Удаляем старую таблицу и переименовываем новую
            self.execute_query('DROP TABLE participants')
            self.execute_query('ALTER TABLE participants_new RENAME TO participants')
        else:
            # Если колонка уже существует, просто создаем таблицу если её нет
            self.execute_query('''
                CREATE TABLE IF NOT EXISTS participants (
                    username TEXT,
                    training_id INTEGER,
                    status TEXT DEFAULT 'ACTIVE',
                    paid INTEGER DEFAULT 0,
                    signup_time TIMESTAMP,
                    FOREIGN KEY (training_id) REFERENCES schedule(training_id)
                )
            ''')

    def add_training(self, channel_id: int, date_time: str, duration: int, kind: str, 
                    location: str, max_participants: int, status: str, price: int) -> int:
        """Добавляет новую тренировку"""
        try:
            self.execute_query('''
                INSERT INTO schedule 
                (channel_id, date_time, duration, kind, location, max_participants, status, price)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (channel_id, date_time, duration, kind, location, max_participants, status, price))
            
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
        """Добавляет участника на тренировку"""
        try:
            # Проверяем количество участников
            current_count = len(self.get_participants_by_training_id(training_id))
            training = self.get_training_details(training_id)
            
            if current_count >= training.max_participants:
                return False
            
            # Добавляем участника с текущим временем
            self.execute_query('''
                INSERT OR IGNORE INTO participants 
                (username, training_id, signup_time) 
                VALUES (?, ?, datetime('now'))
            ''', (username, training_id))
            return True
        except Exception as e:
            print(f"Error adding participant: {e}")
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

    def get_trainings_for_channel(self, channel_id: int) -> List[Training]:
        """Получает список тренировок для конкретной группы"""
        rows = self.fetch_all('''
            SELECT training_id, channel_id, date_time, duration, kind, location, 
                   status, max_participants, price
            FROM schedule 
            WHERE channel_id = ?
            ORDER BY date_time
        ''', (channel_id,))
        
        return [
            Training(
                id=row[0],
                channel_id=row[1],
                date_time=datetime.strptime(row[2], '%Y-%m-%d %H:%M'),
                duration=row[3],
                kind=row[4],
                location=row[5],
                status=row[6],
                max_participants=row[7],
                price=row[8]
            ) for row in rows
        ]

    def get_training_details(self, training_id: int) -> Optional[Training]:
        """Получает детали тренировки по ID"""
        result = self.fetch_one('''
            SELECT training_id, channel_id, date_time, duration, 
                   kind, location, max_participants, status, price
            FROM schedule WHERE training_id = ?
        ''', (training_id,))
        
        if result:
            return Training(
                id=result[0],
                channel_id=result[1],
                date_time=datetime.strptime(result[2], '%Y-%m-%d %H:%M'),
                duration=result[3],
                kind=result[4],
                location=result[5],
                max_participants=result[6],
                status=result[7],
                price=result[8]
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
        """Предлагает место следующему в резерве"""
        try:
            # Получаем следующего в очереди
            next_in_line = self.fetch_one('''
                SELECT username FROM reserve 
                WHERE training_id = ? AND status = 'WAITING'
                ORDER BY position ASC LIMIT 1
            ''', (training_id,))
            
            if next_in_line:
                username = next_in_line[0]
                # Обновляем статус и время предложения
                self.execute_query('''
                    UPDATE reserve 
                    SET status = 'OFFERED', offer_timestamp = datetime('now')
                    WHERE username = ? AND training_id = ?
                ''', (username, training_id))
                return username
            
            return None
        except Exception as e:
            print(f"Error offering spot to reserve: {e}")
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

    def set_payment_status(self, username: str, training_id: int, status: int) -> bool:
        """Устанавливает статус оплаты
        status:
        0 - не оплачено
        1 - ожидает подтверждения
        2 - подтверждено
        """
        try:
            self.execute_query(
                "UPDATE participants SET paid = ? WHERE username = ? AND training_id = ?",
                (status, username, training_id)
            )
            return True
        except Exception as e:
            print(f"Error setting payment status: {e}")
            return False

    def get_payment_status(self, username: str, training_id: int) -> int:
        """Получает статус оплаты тренировки
        Возвращает:
        0 - не оплачено
        1 - ожидает подтверждения
        2 - подтверждено
        """
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

    def confirm_payment(self, username: str, training_id: int) -> bool:
        """Подтверждает оплату тренировки"""
        try:
            self.execute_query(
                "UPDATE participants SET paid = 2 WHERE username = ? AND training_id = ?",
                (username, training_id)
            )
            return True
        except Exception as e:
            print(f"Error confirming payment: {e}")
            return False 

    def mark_payment_pending(self, username: str, training_id: int) -> bool:
        """Отмечает оплату как ожидающую подтверждения"""
        try:
            self.execute_query(
                "UPDATE participants SET paid = 1 WHERE username = ? AND training_id = ?",
                (username, training_id)
            )
            return True
        except Exception as e:
            print(f"Error marking payment as pending: {e}")
            return False 

    def get_all_trainings(self) -> List[Training]:
        """Получает все тренировки"""
        try:
            rows = self.fetch_all('''
                SELECT training_id, channel_id, date_time, duration, kind, 
                       location, status, max_participants, price
                FROM schedule
                ORDER BY date_time
            ''')
            
            trainings = []
            for row in rows:
                try:
                    trainings.append(Training(
                        id=row[0],
                        channel_id=row[1],
                        date_time=datetime.strptime(row[2], '%Y-%m-%d %H:%M'),
                        duration=row[3],
                        kind=row[4],
                        location=row[5],
                        status=row[6],
                        max_participants=row[7],
                        price=row[8]
                    ))
                except Exception as e:
                    print(f"Error parsing training data: {e}, row: {row}")
                    continue
                
            return trainings
        except Exception as e:
            print(f"Error getting all trainings: {e}")
            return [] 

    def get_signup_time(self, username: str, training_id: int) -> Optional[datetime]:
        """Получает время записи участника на тренировку"""
        try:
            result = self.fetch_one(
                "SELECT signup_time FROM participants WHERE username = ? AND training_id = ?",
                (username, training_id)
            )
            if result and result[0]:
                return datetime.strptime(result[0], '%Y-%m-%d %H:%M:%S')
            return None
        except Exception as e:
            print(f"Error getting signup time: {e}")
            return None 
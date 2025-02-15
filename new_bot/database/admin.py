import os
from typing import List, Optional, Tuple
from new_bot.database.base import BaseDB
from new_bot.types import Training, User

class AdminDB(BaseDB):
    def __init__(self, db_path: str = 'admin.db'):
        super().__init__(db_path)

    def _initialize_db(self):
        """Инициализирует базу данных"""
        self.execute_query('''
        CREATE TABLE IF NOT EXISTS admins (
            username TEXT PRIMARY KEY,
            user_id INTEGER,
            payment_details TEXT DEFAULT 'Реквизиты не указаны',
            invite_limit INTEGER DEFAULT 0
        )
        ''')
        self.execute_query('''
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            user_id INTEGER
        )
        ''')
        
        # Проверяем существующие колонки
        columns = self.fetch_all("PRAGMA table_info(admins)")
        column_names = [column[1] for column in columns]
        
        # Добавляем колонку payment_details, если её нет
        if 'payment_details' not in column_names:
            self.execute_query('ALTER TABLE admins ADD COLUMN payment_details TEXT DEFAULT "Реквизиты не указаны"')

        # Добавляем колонку invite_limit, если её нет
        if 'invite_limit' not in column_names:
            self.execute_query('ALTER TABLE admins ADD COLUMN invite_limit INTEGER DEFAULT 0')

        # Обновляем существующие записи
        self.execute_query('UPDATE admins SET invite_limit = 0 WHERE invite_limit IS NULL')

    def is_admin(self, username: str) -> bool:
        return self.fetch_one("SELECT 1 FROM admins WHERE username = ?", (username,)) is not None

    def add_admin(self, username: str) -> None:
        self.execute_query("INSERT INTO admins (username) VALUES (?)", (username,))

    def remove_admin(self, username: str) -> None:
        self.execute_query("DELETE FROM admins WHERE username = ?", (username,))

    def get_all_admins(self) -> List[Tuple[str]]:
        return self.fetch_all("SELECT username FROM admins")
    
    def add_user(self, user_id: int, username: str) -> None:
        self.execute_query(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", 
            (user_id, username)
        )

    def get_all_users(self) -> List[Tuple[int]]:
        return self.fetch_all("SELECT user_id FROM users")
    
    def get_user_info(self, user_id: int) -> Optional[User]:
        result = self.fetch_one(
            "SELECT user_id, username FROM users WHERE user_id = ?", 
            (user_id,)
        )
        if not result:
            return None
        return User(
            id=result[0],
            username=result[1],
            is_admin=self.is_admin(result[1])
        )

    def get_user(self, user_id: int) -> Optional[User]:
        result = self.fetch_one(
            "SELECT user_id, username FROM users WHERE user_id = ?", 
            (user_id,)
        )
        if not result:
            return None
        return User(
            id=result[0],
            username=result[1],
            is_admin=self.is_admin(result[1])
        )

    def set_payment_details(self, username: str, details: str):
        """Устанавливает реквизиты для оплаты"""
        self.execute_query(
            "UPDATE admins SET payment_details = ? WHERE username = ?",
            (details, username)
        )
        
    def get_payment_details(self, username: str) -> str:
        """Получает реквизиты для оплаты"""
        result = self.fetch_one(
            "SELECT payment_details FROM admins WHERE username = ?",
            (username,)
        )
        return result[0] if result else "Реквизиты не указаны"

    def get_user_id(self, username: str) -> Optional[int]:
        """Получает user_id пользователя по его username"""
        print(f"Ищем user_id для пользователя: {username}")  # Отладка
        result = self.fetch_one(
            "SELECT user_id FROM users WHERE username = ?",
            (username,)
        )
        print(f"Результат запроса: {result}")  # Отладка
        return result[0] if result else None

    def get_user(self, username: str) -> Tuple[str, int, str]:
        """Получает информацию о пользователе"""
        return self.fetch_one(
            "SELECT username, user_id, role FROM users WHERE username = ?",
            (username,)
        )

    def set_invite_limit(self, username: str, limit: int) -> None:
        """Устанавливает лимит приглашений для админа"""
        self.execute_query(
            "UPDATE admins SET invite_limit = ? WHERE username = ?",
            (limit, username)
        )
        
    def get_invite_limit(self, username: str) -> int:
        """Получает лимит приглашений админа"""
        result = self.fetch_one(
            "SELECT invite_limit FROM admins WHERE username = ?",
            (username,)
        )
        return result[0] if result else 0

    def get_training_details(self, training_id: int) -> Optional[Training]:
        result = self.fetch_one('''
            SELECT training_id, date_time, duration, 
            kind, location, max_participants, status
            FROM schedule WHERE training_id = ?
        ''', (training_id,))
        if not result:
            return None
        return Training(
            id=result[0],
            date_time=result[1],
            duration=result[2],
            kind=result[3],
            location=result[4],
            max_participants=result[5],
            status=result[6]
        ) 
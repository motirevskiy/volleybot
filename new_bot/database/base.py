from typing import Any, List, Optional, Tuple
import sqlite3
from contextlib import contextmanager
import os

@contextmanager
def db_connection(db_name):
    conn = sqlite3.connect(db_name)
    try:
        yield conn
    finally:
        conn.close()

class BaseDB:
    def __init__(self, db_path: str = 'bot.db'):
        # Создаем папку data, если её нет
        data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        # Путь к базе данных в папке data
        self.db_path = os.path.join(data_dir, db_path)
        self.connection = None
        self.cursor = None
        self._connect()
        self._initialize_db()

    def _connect(self):
        """Устанавливает соединение с базой данных"""
        self.connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.cursor = self.connection.cursor()

    def execute_query(self, query: str, params: tuple = ()) -> Optional[int]:
        """Выполняет запрос и возвращает id последней вставленной записи для INSERT"""
        self.cursor.execute(query, params)
        self.connection.commit()
        return self.cursor.lastrowid if query.strip().upper().startswith('INSERT') else None

    def fetch_all(self, query: str, params: tuple = ()) -> List[Tuple]:
        self.cursor.execute(query, params)
        return self.cursor.fetchall()

    def fetch_one(self, query: str, params: tuple = ()) -> Optional[Tuple]:
        self.cursor.execute(query, params)
        return self.cursor.fetchone()

    def _initialize_db(self) -> None:
        """Метод для инициализации базы данных. Должен быть переопределен в наследниках."""
        self.create_training_table()

    def create_training_table(self):
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS schedule (
                training_id INTEGER PRIMARY KEY AUTOINCREMENT,
                date_time TEXT,
                duration INTEGER,
                kind TEXT,
                location TEXT,
                status TEXT,
                max_participants INTEGER DEFAULT 10,
                price INTEGER DEFAULT 0
            )
        ''')

    def __del__(self):
        if hasattr(self, 'cursor'):
            self.cursor.close()
        if hasattr(self, 'connection'):
            self.connection.close() 
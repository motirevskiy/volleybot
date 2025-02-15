from typing import List, Optional, Tuple
from new_bot.database.base import BaseDB

class ChannelDB(BaseDB):
    def __init__(self):
        super().__init__('channels.db')

    def _initialize_db(self):
        """Инициализирует базу данных для каналов"""
        self.execute_query('''
            CREATE TABLE IF NOT EXISTS channels (
                channel_id INTEGER PRIMARY KEY,
                title TEXT,
                added_date DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        ''')

    def add_channel(self, channel_id: int, title: str) -> bool:
        """Добавляет новый канал"""
        try:
            self.execute_query(
                "INSERT OR IGNORE INTO channels (channel_id, title) VALUES (?, ?)",
                (channel_id, title)
            )
            return True
        except Exception as e:
            print(f"Error adding channel: {e}")
            return False

    def remove_channel(self, channel_id: int) -> bool:
        """Удаляет канал"""
        try:
            self.execute_query("DELETE FROM channels WHERE channel_id = ?", (channel_id,))
            return True
        except Exception as e:
            print(f"Error removing channel: {e}")
            return False

    def get_channel(self, channel_id: int) -> Optional[Tuple[int, str]]:
        """Получает информацию о канале"""
        return self.fetch_one(
            "SELECT channel_id, title FROM channels WHERE channel_id = ?",
            (channel_id,)
        )

    def get_all_channels(self) -> List[Tuple[int, str]]:
        """Получает список всех каналов"""
        return self.fetch_all("SELECT channel_id, title FROM channels")

    def channel_exists(self, channel_id: int) -> bool:
        """Проверяет существование канала"""
        result = self.fetch_one(
            "SELECT 1 FROM channels WHERE channel_id = ?",
            (channel_id,)
        )
        return bool(result) 
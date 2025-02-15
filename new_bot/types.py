from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Union
from telebot.types import Message, CallbackQuery

@dataclass
class Training:
    id: int
    date_time: datetime
    duration: int
    kind: str
    location: str
    status: str
    price: int
    max_participants: int = 10
    participants: Optional[List[str]] = None

    @classmethod
    def from_db_row(cls, row: tuple) -> 'Training':
        """
        Создает объект Training из кортежа БД.
        Ожидаемый порядок в кортеже:
        (date_time, duration, type, location, status, max_participants)
        """
        date_time, duration, type_, location, status, max_participants = row
        return cls(
            id=0,
            date_time=datetime.strptime(date_time, '%Y-%m-%d %H:%M'),
            duration=int(duration),
            kind=type_,
            location=location,
            status=status,
            price=0,
            max_participants=int(max_participants),
        )

@dataclass
class User:
    id: int
    username: str
    is_admin: bool = False

@dataclass
class TrainingData:
    """Класс для хранения данных при создании/редактировании тренировки"""
    date_time: Optional[str] = None
    duration: Optional[int] = None
    kind: Optional[str] = None
    location: Optional[str] = None
    max_participants: Optional[int] = None
    price: Optional[int] = None

    def is_complete(self) -> bool:
        return all([
            self.date_time, 
            self.duration, 
            self.kind,
            self.location,
            self.max_participants,
            self.price
        ])

    def to_tuple(self) -> tuple:
        return (
            self.date_time,
            self.duration,
            self.kind,
            self.location,
            self.max_participants,
            self.price
        )

# Типы для обработчиков
HandlerType = Union[Message, CallbackQuery]
BotType = 'telebot.TeleBot'  # type: ignore 
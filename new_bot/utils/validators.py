from datetime import datetime
from typing import Tuple, Optional

class ValidationError(Exception):
    """Исключение для ошибок валидации"""
    pass

def validate_datetime(date_str: str) -> datetime:
    """
    Проверяет и преобразует строку с датой и временем.
    
    Args:
        date_str: Строка в формате 'YYYY-MM-DD HH:MM'
        
    Returns:
        datetime: Объект datetime
        
    Raises:
        ValidationError: Если формат даты неверный или дата в прошлом
    """
    try:
        date_time = datetime.strptime(date_str, '%Y-%m-%d %H:%M')
        if date_time < datetime.now():
            raise ValidationError("Дата не может быть в прошлом")
        return date_time
    except ValueError:
        raise ValidationError(
            "Неверный формат даты. Используйте формат: YYYY-MM-DD HH:MM\n"
            "Например: 2024-02-20 18:30"
        )

def validate_duration(duration_str: str) -> int:
    """
    Проверяет длительность тренировки.
    
    Args:
        duration_str: Строка с числом минут
        
    Returns:
        int: Длительность в минутах
        
    Raises:
        ValidationError: Если длительность некорректная
    """
    try:
        duration = int(duration_str)
        if duration <= 0:
            raise ValidationError("Длительность должна быть положительным числом")
        if duration > 180:  # максимум 3 часа
            raise ValidationError("Длительность не может быть больше 180 минут")
        return duration
    except ValueError:
        raise ValidationError("Длительность должна быть числом")

def validate_kind(kind_str: str) -> str:
    """
    Проверяет тип тренировки.
    
    Args:
        kind_str: Строка с типом тренировки
        
    Returns:
        str: Проверенный тип тренировки
        
    Raises:
        ValidationError: Если тип некорректный
    """
    if not kind_str or len(kind_str) > 50:
        raise ValidationError("Некорректный тип тренировки")
    return kind_str.strip()

def validate_location(location_str: str) -> str:
    """
    Проверяет место проведения тренировки.
    
    Args:
        location_str: Строка с местом проведения
        
    Returns:
        str: Проверенное место проведения
        
    Raises:
        ValidationError: Если место некорректное
    """
    if not location_str.strip():
        raise ValidationError("Место проведения не может быть пустым")
    if len(location_str) > 100:
        raise ValidationError("Место проведения слишком длинное (максимум 100 символов)")
    return location_str.strip() 
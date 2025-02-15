from typing import Type, List, Tuple
from datetime import datetime
from new_bot.types import Training

def create_training_message(training: Training, admin_id: str) -> str:
    status_text = "Открыта" if training.status == "OPEN" else "Закрыта"
    
    # Получаем текущее количество участников
    from new_bot.database.trainer import TrainerDB
    trainer_db = TrainerDB(admin_id)
    current_participants = len(trainer_db.get_participants_by_training_id(training.id))
    
    return (
        f"- {training.date_time.strftime('%Y-%m-%d %H:%M')} | "
        f"{training.kind} | {training.duration} минут | "
        f"{training.location} | "
        f"💰 {training.price}₽ | "
        f"Участники: {current_participants}/{training.max_participants} | "
        f"Запись {status_text}\n"
    )

def create_schedule_message(trainings: List[Training], admins_map: dict) -> str:
    if not trainings:
        return "Нет доступных тренировок"

    message = "Расписание тренировок:\n"
    
    for training in trainings:
        message += f"- {training.date_time.strftime('%Y-%m-%d %H:%M')} | "
        message += f"{training.kind} | {training.duration} минут | "
        message += f"{training.location} | "
        message += f"💰 {training.price}₽ | "
        # Получаем текущее количество участников
        from new_bot.database.trainer import TrainerDB
        trainer_db = TrainerDB(admins_map.get(training.id))
        current_participants = len(trainer_db.get_participants_by_training_id(training.id))
        message += f"Участники: {current_participants}/{training.max_participants} | "
        message += f"Запись {'Открыта' if training.status == 'OPEN' else 'Закрыта'}\n"
    
    return message

def create_open_training_message(admin_username: str, training: Training) -> str:
    from new_bot.database.trainer import TrainerDB
    from new_bot.database.admin import AdminDB
    trainer_db = TrainerDB(admin_username)
    admin_db = AdminDB()
    current_participants = len(trainer_db.get_participants_by_training_id(training.id))
    payment_details = admin_db.get_payment_details(admin_username)
    
    message = (
        f"Открыта запись на тренировку у @{admin_username}:\n"
        f"📅 Дата: {training.date_time.strftime('%d.%m.%Y %H:%M')}\n"
        f"🏋️‍♂️ Тип: {training.kind}\n"
        f"⏱ Длительность: {training.duration} минут\n"
        f"📍 Место: {training.location}\n"
        f"💰 Стоимость: {training.price}₽\n"
        f"👥 Участники: {current_participants}/{training.max_participants}\n"
        f"\n💳 Реквизиты для оплаты:\n{payment_details}"
    )
    return message

def format_participant(username: str, paid_status: int, number: int) -> str:
    """Форматирует строку с участником и статусом оплаты"""
    status_emoji = {
        1: "⏳",  # ожидает подтверждения оплаты
        2: "✅"   # оплата подтверждена
    }
    status = status_emoji.get(paid_status, "")  # Если нет оплаты (0), то пустая строка
    return f"{number}. {status} @{username}" 
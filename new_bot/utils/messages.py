from typing import List
from datetime import datetime
from new_bot.types import Training

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
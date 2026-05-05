import logging
import os
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv
from telebot import TeleBot

from exceptions import (
    APIRequestError, APIResponseError, InvalidHomeworkStatusError
)


load_dotenv()


TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
PRACTICUM_TOKEN = os.getenv("PRACTICUM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}


HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

KEYS_IN_RESPONSE = ('homeworks', 'current_date')
REQUIRED_KEYS_IN_HOMEWORK = ('status', 'homework_name')

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler(stream=sys.stdout)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

handler.setFormatter(formatter)

logger.addHandler(handler)


def check_tokens() -> None:
    """
    Проверяет доступность переменных окружения.

    Если отсутствует хотя бы одна переменная окружения — лог CRITICAL.
    """
    env_vars = {
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }

    if not all(env_vars .values()):
        missing = [name for name, value in env_vars.items() if not value]
        logger.critical('Отсутствуют переменные окружения: %s', missing)
        sys.exit()


def send_message(bot: TeleBot, message: str) -> None:
    """
    Отправляет сообщения в чат по TELEGRAM_CHAT_ID.

    Аргументы:
        bot (TeleBot): экземпляр класса TeleBot, телеграм-бот
        message (str): сообщение пользователю

    Если сообщение не отправилось — лог ERROR.
    """
    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logger.debug('Сообщение отправлено в чат!')
    except Exception as error:
        logger.error('Ошибка отправки сообщения: %s', error)


def get_api_answer(timestamp: int) -> dict[str, Any]:
    """
    Делает запрос к API Практикум Домашка.

    Аргументы:
        timestamp (int): временная метка

    Возвращает:
        dict[str, Any]: ответ API в виде словаря
    """
    try:
        response = requests.get(
            ENDPOINT,
            headers=HEADERS,
            params={'from_date': timestamp}
        )
    except Exception as error:
        message = f'Ошибка при запросе к API: {error}'
        logger.error(message)
        raise APIRequestError(message)

    if response.status_code != 200:
        message = (
            f'Эндпоинт {ENDPOINT} недоступен. '
            f'Код ответа API: {response.status_code}'
        )
        logger.error(message)
        raise APIRequestError(message)

    try:
        return response.json()
    except Exception as error:
        message = f'Ошибка преобразования ответа API в JSON: {error}'
        logger.error(message)
        raise APIResponseError(message)


def check_response(response: dict[str, Any]) -> None:
    """
    Проверяет ответ API на соответствие документации.

    Аргументы:
        response: dict[str, Any]
    """
    if not isinstance(response, dict):
        message = 'Ответ API должен быть dict'
        logger.error(message)
        raise TypeError(message)

    for key in KEYS_IN_RESPONSE:
        if key not in response:
            message = f'В ответе API нет ключа: {key}.'
            logger.error(message)
            raise KeyError(message)

    if not isinstance(response.get('homeworks'), list):
        message = ('homeworks должен быть списком')
        logger.error(message)
        raise TypeError(message)


def parse_status(homework: dict[str, Any]) -> str:
    """
    Извлекает из информации о конкретной домашней работе статус этой работы.

    Аргументы:
        homework (dict[str, Any]): один элемент из списка домашних работ

    Возвращает:
        str: статус домашней работы.
    """
    if not isinstance(homework, dict):
        message = 'Некорректный тип домашки'
        logger.error(message)
        raise TypeError(message)

    for key in REQUIRED_KEYS_IN_HOMEWORK:
        if key not in homework:
            message = f'В домашке отсутствует ключ: {key}.'
            logger.error(message)
            raise KeyError(message)

    status = homework['status']

    if status not in HOMEWORK_VERDICTS:
        message = f'Статус {status} не предусмотрен!'
        logger.error(message)
        raise InvalidHomeworkStatusError(message)

    homework_name = homework['homework_name']
    verdict = HOMEWORK_VERDICTS[status]
    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main():
    """
    Основная логика работы бота.

    1. Получить response
    2. Проверить response
    3. Достать список домашек homeworks
    4. Если homeworks пуст, то лог DEBUG. Иначе берем первую домашку.
    5. Парсим статус домашки.
    6. Отправляем сообщение в бота.
    7. Обновляем временную метку timestamp.
    """
    check_tokens()

    bot = TeleBot(token=TELEGRAM_TOKEN)
    timestamp = int(time.time())

    last_error_type = None

    while True:
        try:
            response = get_api_answer(timestamp)
            check_response(response)

            homeworks = response['homeworks']

            if not homeworks:
                logger.debug('Нет новых статусов домашек!')
            else:
                homework = homeworks[0]
                message = parse_status(homework)
                send_message(bot, message)

            timestamp = response['current_date']
            last_error_type = None

        except Exception as error:
            error_type = error.__class__
            message = f"Сбой в работе программы: {error}"
            logger.error(message)

            if error_type != last_error_type:
                send_message(bot, message)
                last_error_type = error_type

        time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    main()

"""Telegram-бот для проверки статуса домашних работ."""

from http import HTTPStatus
import logging
import os
import sys
import time
from typing import Any

import requests
from dotenv import load_dotenv
from telebot import TeleBot, apihelper

from exceptions import (
    APIRequestError,
    APIResponseError,
    InvalidHomeworkStatusError,
    MissingEnvironmentVariableError,
)


load_dotenv()


TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
PRACTICUM_TOKEN = os.getenv('PRACTICUM_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

RETRY_PERIOD = 600
ENDPOINT = 'https://practicum.yandex.ru/api/user_api/homework_statuses/'
HEADERS = {'Authorization': f'OAuth {PRACTICUM_TOKEN}'}

HOMEWORK_VERDICTS = {
    'approved': 'Работа проверена: ревьюеру всё понравилось. Ура!',
    'reviewing': 'Работа взята на проверку ревьюером.',
    'rejected': 'Работа проверена: у ревьюера есть замечания.'
}

REQUIRED_KEYS_IN_HOMEWORK = ('status', 'homework_name')

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = logging.StreamHandler(stream=sys.stdout)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)


def check_tokens() -> None:
    """
    Проверяет наличие обязательных переменных окружения.

    :raises MissingEnvironmentVariableError: Если отсутствует хотя бы
        одна обязательная переменная окружения.
    """
    env_vars = {
        'TELEGRAM_TOKEN': TELEGRAM_TOKEN,
        'PRACTICUM_TOKEN': PRACTICUM_TOKEN,
        'TELEGRAM_CHAT_ID': TELEGRAM_CHAT_ID,
    }

    missing_vars = [
        name for name, value in env_vars.items()
        if not value
    ]

    if missing_vars:
        message = (f'Отсутствуют переменные окружения: {missing_vars}')
        logger.critical(message)
        raise MissingEnvironmentVariableError(message)


def send_message(bot: TeleBot, message: str) -> bool:
    """
    Отправляет сообщения в чат по TELEGRAM_CHAT_ID.

    :param bot: Экземпляр Telegram-бота.
    :param message: Текст сообщения.
    :return: True, если сообщение отправлено успешно, иначе False.
    """
    logger.debug('Отправляем сообщение в Telegram: %s', message)

    try:
        bot.send_message(TELEGRAM_CHAT_ID, message)
        logger.debug('Сообщение успешно отправлено в чат!')
        return True

    except (apihelper.ApiException, requests.RequestException) as error:
        logger.error('Ошибка отправки сообщения: %s', error)
        return False


def get_api_answer(timestamp: int) -> dict[str, Any]:
    """
    Делает запрос к API.

    :param timestamp: Временная метка последнего запроса.
    :return: Ответ API в виде словаря.
    :raises APIRequestError: Если запрос завершился ошибкой.
    :raises APIResponseError: Если ответ API не удалось преобразовать в JSON.
    """
    request_params = {
        'url': ENDPOINT,
        'headers': HEADERS,
        'params': {'from_date': timestamp},
    }

    logger.debug(
        'Отправляем запрос к API. Адрес: %(url)s, '
        'Заголовки: %(headers)s, Параметры: %(params)s',
        request_params,
    )

    try:
        response = requests.get(**request_params)
    except requests.RequestException as error:
        raise APIRequestError(f'Ошибка при запросе к API: {error}')

    if response.status_code != HTTPStatus.OK:
        raise APIRequestError(
            f'API вернул неожиданный статус-код: {response.status_code}'
        )

    try:
        return response.json()
    except ValueError as error:
        raise APIResponseError(
            f'Ошибка преобразования ответа API в JSON: {error}'
        )


def check_response(response: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Проверяет ответ API на соответствие документации.

    :param response: Ответ API.
    :return: Список домашних работ.
    :raises TypeError: Если ответ API или список домашних работ
        имеют некорректный тип.
    :raises KeyError: Если в ответе API отсутствует ключ homeworks.
    """
    if not isinstance(response, dict):
        raise TypeError(f'Ожидался dict, получен {type(response)}')

    if 'homeworks' not in response:
        raise KeyError('В ответе API отсутствует ключ homeworks')

    homeworks = response.get('homeworks')

    if not isinstance(homeworks, list):
        raise TypeError(
            f'homeworks должен быть list, получен {type(homeworks)}'
        )

    if 'current_date' not in response:
        logger.error('В ответе API отсутствует ключ current_date')

    return homeworks


def parse_status(homework: dict[str, Any]) -> str:
    """
    Формирует сообщение о статусе домашней работы.

    :param homework: Данные одной домашней работы.
    :return: Сообщение о статусе домашней работы.
    :raises TypeError: Если данные домашней работы имеют некорректный тип.
    :raises KeyError: Если в данных домашней работы отсутствуют нужные ключи.
    :raises InvalidHomeworkStatusError: Если статус домашней работы неизвестен.
    """
    if not isinstance(homework, dict):
        raise TypeError(f'Ожидался dict, получен {type(homework)}')

    for key in REQUIRED_KEYS_IN_HOMEWORK:
        if key not in homework:
            raise KeyError(f'В домашке отсутствует ключ: {key}')

    status = homework['status']

    if status not in HOMEWORK_VERDICTS:
        raise InvalidHomeworkStatusError(
            f'Статус {status} не предусмотрен!'
        )

    homework_name = homework['homework_name']
    verdict = HOMEWORK_VERDICTS[status]

    return f'Изменился статус проверки работы "{homework_name}". {verdict}'


def main() -> None:
    """
    Запускает основной цикл работы бота.

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
            homeworks = check_response(response)

            should_update_timestamp = False

            if not homeworks:
                logger.debug('Нет новых статусов домашек!')
                should_update_timestamp = True
            else:
                homework = homeworks[0]
                message = parse_status(homework)
                should_update_timestamp = send_message(bot, message)

            if should_update_timestamp:
                timestamp = response.get('current_date', timestamp)

            last_error_type = None

        except Exception as error:
            error_type = type(error)
            message = f'Сбой в работе программы: {error}'
            logger.error(message)

            if error_type != last_error_type:
                send_message(bot, message)
                last_error_type = error_type

        finally:
            time.sleep(RETRY_PERIOD)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info('Бот остановлен вручную')
    except Exception as error:
        logger.critical('Критическая ошибка: %s', error)
        sys.exit()

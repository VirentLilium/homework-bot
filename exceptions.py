"""Модуль с исключениями."""


class MissingEnvironmentVariableError(Exception):
    """Отсутствуют обязательные переменные окружения."""


class APIRequestError(Exception):
    """Ошибка запроса к API."""


class APIResponseError(Exception):
    """Некорректный ответ API."""


class InvalidHomeworkStatusError(Exception):
    """Неизвестный статус домашней работы."""

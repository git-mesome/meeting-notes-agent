"""화면에 그대로 보여 줄 오류. 서비스 계층은 이 오류를 던지고, 웹 계층이 HTTP 응답으로 바꾼다(main.py)."""


class AppError(Exception):
    status = 400

    def __init__(self, message):
        super().__init__(message)
        self.message = message


class NotFound(AppError):
    status = 404


class Conflict(AppError):
    status = 409


class TooLarge(AppError):
    status = 413


class Invalid(AppError):
    status = 422


class Upstream(AppError):
    """Claude API나 이슈 트래커 같은 바깥 서비스가 응답하지 않았다."""

    status = 502

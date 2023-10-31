import sys
import traceback


class LogEntry:
    def __init__(self, message, details=None):
        self.message = message
        self.details = details


class ChadLogger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ChadLogger, cls).__new__(cls)
            cls._instance.log = []
        return cls._instance

    def log_message(self, message, details=None):
        print(message)
        self.log.append(LogEntry(message, details))

    def query_logs(self):
        return "\n".join([f"{index}: {x.message}" for index, x in enumerate(self.log[:10])])

    def clear_logs(self):
        self.log = []

    @staticmethod
    def log(message):
        ChadLogger().log_message(message)

    def log_exception(self, exc_type, exc_value, exc_traceback):
        # Format the exception as a string
        exception = traceback.format_exception(
            exc_type, exc_value, exc_traceback)
        formatted_exception = "".join(
            exception
        )

        # Log the formatted exception
        self.log_message(exception[-1:][0], formatted_exception)

# Set the custom exception hook


def log_exception_to_chad_logger(exc_type, exc_value, exc_traceback):
    ChadLogger().log_exception(exc_type, exc_value, exc_traceback)


sys.excepthook = log_exception_to_chad_logger

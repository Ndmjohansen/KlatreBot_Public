import sys
import traceback


class LogEntry:
    count = -1

    def __init__(self, message, details=None):
        self.message = message
        self.details = details
        LogEntry.count += 1
        self.index = LogEntry.count


class ChadLogger:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ChadLogger, cls).__new__(cls)
            cls._instance.log = []
        return cls._instance

    def log_message(self, message, details=None):
        print(message, file=sys.stderr)  # Send to stderr instead of stdout
        self.log.append(LogEntry(message, details))

    def query_logs(self, count=10):
        return_val = "```"
        return_val += "\n".join([f"{x.index}: {x.message}" for
                                x in self.log[-int(count):]])
        return_val += "```"
        print(f"message log length: {len(return_val)}")
        return ChadLogger.trim_too_long_messages(return_val)

    def query_detailed_logs(self, count=10):
        return_val = "```"
        return_val += "\n".join([f"{x.index}: {x.details}" for
                                x in self.log[-int(count):]])
        return_val += "```"
        print(f"detail log length: {len(return_val)}")
        return ChadLogger.trim_too_long_messages(return_val)

    def query_specific_log(self, index):
        return_val = "```"
        x = self.log[int(index)]
        return_val += f"{x.index}: {x.message}"
        return_val += "```"
        print(f"message log length: {len(return_val)}")
        return ChadLogger.trim_too_long_messages(return_val)

    def query_specific_detailed_log(self, index):
        return_val = "```"
        x = self.log[int(index)]
        return_val += f"{x.index}: {x.details}"
        return_val += "```"
        print(f"detail log length: {len(return_val)}")
        return ChadLogger.trim_too_long_messages(return_val)

    @staticmethod
    def trim_too_long_messages(message):
        return_val = message
        original_length = len(return_val)
        if original_length > 1800:
            return_val = return_val[:1800]
            return_val += f"\n... message too long: {original_length}```"
        return return_val

    def clear_logs(self):
        self.log = []

    @staticmethod
    def log(message):
        ChadLogger().log_message(message)

    def log_exception(self, exc_type, exc_value, exc_traceback):
        # Format the exception as a string
        exception = traceback.format_exception(
            exc_type, exc_value, exc_traceback)

        only_direct_traceback = []
        for e in exception:
            if 'The above exception was the direct cause of the following exception:' in e:
                break
            else:
                only_direct_traceback.append(e)

        formatted_exception = "\n".join(
            only_direct_traceback
        )

        # Log the formatted exception
        self.log_message(exception[-1:][0], formatted_exception)

# Set the custom exception hook


def log_exception_to_chad_logger(exc_type, exc_value, exc_traceback):
    ChadLogger().log_exception(exc_type, exc_value, exc_traceback)


sys.excepthook = log_exception_to_chad_logger

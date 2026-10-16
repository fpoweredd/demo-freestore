import threading
import time

from decouple import config

EPOCH = 1775001600000
WORKER_ID = config("SNOWFLAKE_WORKER_ID", default=1, cast=int)

_lock = threading.Lock()
_sequence = 0
_last_timestamp = -1


def _timestamp_ms() -> int:
    return int(time.time() * 1000) - EPOCH


def generate_snowflake_id() -> int:
    global _sequence, _last_timestamp

    with _lock:
        timestamp = _timestamp_ms()

        if timestamp < _last_timestamp:
            timestamp = _last_timestamp

        if timestamp == _last_timestamp:
            _sequence = (_sequence + 1) & 0x1FFF
            if _sequence == 0:
                while timestamp <= _last_timestamp:
                    timestamp = _timestamp_ms()
        else:
            _sequence = 0

        _last_timestamp = timestamp
        return (timestamp << 23) | (WORKER_ID << 13) | _sequence

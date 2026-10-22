import logging
import traceback
from pathlib import Path


def exception_details(exc_info):
    """Record stack locations without messages, source lines or local variables."""
    if not exc_info or not exc_info[0]:
        return {}
    return {
        'exception': exc_info[0].__name__,
        'pile': [
            {'fichier': Path(frame.filename).name, 'ligne': frame.lineno, 'fonction': frame.name}
            for frame in traceback.extract_tb(exc_info[2])[-12:]
        ],
    }


class JournalErrorHandler(logging.Handler):
    def emit(self, record):
        try:
            from .journal import record_event
            request = getattr(record, 'request', None)
            details = {'logger': record.name, 'statut': getattr(record, 'status_code', None)}
            if request:
                details['route'] = request.path[:300]
            details.update(exception_details(record.exc_info))
            record_event('system', 'system.error', 'Une erreur technique a été rencontrée.', level='ERROR', details=details)
        except Exception:
            # No exception text, local variables, request body or recursive logs.
            pass

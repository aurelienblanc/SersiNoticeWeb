import logging
import traceback
from pathlib import Path


class JournalErrorHandler(logging.Handler):
    def emit(self, record):
        try:
            from .journal import record_event
            request = getattr(record, 'request', None)
            details = {'logger': record.name, 'statut': getattr(record, 'status_code', None)}
            if request:
                details['route'] = request.path[:300]
            if record.exc_info and record.exc_info[0]:
                details['exception'] = record.exc_info[0].__name__
                details['pile'] = [{'fichier': Path(frame.filename).name, 'ligne': frame.lineno, 'fonction': frame.name}
                                  for frame in traceback.extract_tb(record.exc_info[2])[-12:]]
            record_event('system', 'system.error', 'Une erreur technique a été rencontrée.', level='ERROR', details=details)
        except Exception:
            # No exception text, local variables, request body or recursive logs.
            pass

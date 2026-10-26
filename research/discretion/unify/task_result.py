"""Execution outcomes never manufacture field content such as '未提及'."""
from __future__ import annotations

from progress import classify_error


def failure_record(record_id, exc):
    category = classify_error(str(exc))
    status = ('invalid' if isinstance(exc, (ValueError, TypeError)) else 'transport_failed'
              if category in {'auth','balance','rate_limit','timeout','server','empty'}
              or 'unknown_remote_outcome' in str(exc) else 'unresolved')
    return {'id': record_id, 'status': status, 'error_type': type(exc).__name__,
            'category': category, 'reason': str(exc)[:500], 'release_approved': False}

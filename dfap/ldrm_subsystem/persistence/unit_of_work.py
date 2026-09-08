"""Atomic service mutations and durable failure auditing."""
import inspect
from functools import wraps
from dfap.ldrm_subsystem.policy.access_policy import AccessDenied


def atomic(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            with self.repository.transaction():
                return method(self, *args, **kwargs)
        except Exception as error:
            # Outside the failed transaction, so denied attempts are retained.
            bound = inspect.signature(method).bind(self, *args, **kwargs).arguments
            actor = next((bound[k] for k in ('actor_id', 'created_by', 'reviewer_id', 'approver_id', 'signer_id', 'dispatched_by', 'verified_by') if k in bound), 'unknown')
            # A security decision recorded inside the failed transaction would be
            # rolled back with it. Services attach it to the error instead so it
            # is written durably here, after the rollback.
            deferred = getattr(error, 'audit_event', None)
            if deferred is not None and not getattr(error, 'audit_recorded', False):
                self.audit_adapter.log_event(*deferred)
                error.audit_recorded = True
                raise
            if isinstance(error, AccessDenied):
                self.audit_adapter.log_security_violation(str(error), error.actor_id, error.context)
                error.audit_recorded = True
            elif isinstance(error, PermissionError):
                self.audit_adapter.log_security_violation(str(error), actor, {'target_id': bound.get('request_id', 'GLOBAL')})
                error.audit_recorded = True
            else:
                self.audit_adapter.log_event('OPERATION_FAILED', 'LawfulDataRequest', bound.get('request_id', 'GLOBAL'), actor,
                                             {'operation': method.__name__, 'error_type': type(error).__name__})
            raise
    return wrapped

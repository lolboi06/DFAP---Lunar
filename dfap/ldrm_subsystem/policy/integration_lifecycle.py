"""Backend-enforced lifecycle for provider integration profiles (DFAP Stage 3 §6).

A provider integration advances one controlled step at a time. Arbitrary jumps
are refused by the backend, so no frontend, API payload or model output can move
an integration to PRODUCTION_ACTIVE without every intermediate human decision
being recorded first.
"""
from dfap.ldrm_subsystem.domain.enums import ProviderIntegrationStatus as S


class InvalidIntegrationTransitionError(ValueError):
    def __init__(self, current, target, reason=None):
        self.current, self.target = current, target
        super().__init__(reason or f'Integration transition {_v(current)} -> {_v(target)} is not permitted')


class IntegrationActivationError(ValueError):
    """Raised when production activation prerequisites are not satisfied."""


def _v(status):
    return getattr(status, 'value', str(status))


class IntegrationStateMachine:
    """The forward path is strictly sequential; only recorded human decisions advance it."""

    FORWARD_PATH = [
        S.DRAFT,
        S.DOCUMENTATION_VERIFIED,
        S.SANDBOX_CONFIGURED,
        S.CONTRACT_TESTED,
        S.SECURITY_REVIEWED,
        S.AGENCY_APPROVED,
        S.PROVIDER_APPROVED,
        S.PRODUCTION_ACTIVE,
    ]

    # Any live integration may be suspended, revoked or marked expired.
    _INTERRUPTS = {S.SUSPENDED, S.EXPIRED, S.REVOKED}

    _ALLOWED = {
        S.DRAFT: {S.DOCUMENTATION_VERIFIED, S.REVOKED},
        S.DOCUMENTATION_VERIFIED: {S.SANDBOX_CONFIGURED, S.DRAFT} | _INTERRUPTS,
        S.SANDBOX_CONFIGURED: {S.CONTRACT_TESTED, S.DRAFT} | _INTERRUPTS,
        S.CONTRACT_TESTED: {S.SECURITY_REVIEWED, S.SANDBOX_CONFIGURED} | _INTERRUPTS,
        S.SECURITY_REVIEWED: {S.AGENCY_APPROVED, S.CONTRACT_TESTED} | _INTERRUPTS,
        S.AGENCY_APPROVED: {S.PROVIDER_APPROVED, S.SECURITY_REVIEWED} | _INTERRUPTS,
        S.PROVIDER_APPROVED: {S.PRODUCTION_ACTIVE, S.AGENCY_APPROVED} | _INTERRUPTS,
        S.PRODUCTION_ACTIVE: set(_INTERRUPTS),
        # Suspension is reversible by an administrator; revocation is terminal.
        S.SUSPENDED: {S.PROVIDER_APPROVED, S.REVOKED, S.EXPIRED},
        S.EXPIRED: {S.DOCUMENTATION_VERIFIED, S.REVOKED},
        S.REVOKED: set(),
    }

    # Environments an integration may occupy at each status. A MOCK integration
    # can never reach PRODUCTION_ACTIVE, and a PRODUCTION integration cannot
    # claim to be sandbox-configured without also being a production profile.
    from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment as _E
    _TERMINAL_PRODUCTION_ONLY = {S.PRODUCTION_ACTIVE}

    @classmethod
    def can_transition(cls, current, target):
        return target in cls._ALLOWED.get(_status(current), set())

    @classmethod
    def validate_transition(cls, current, target, environment=None):
        current, target = _status(current), _status(target)
        if current == target:
            raise InvalidIntegrationTransitionError(current, target, f'Integration is already {_v(target)}')
        if not cls.can_transition(current, target):
            raise InvalidIntegrationTransitionError(current, target)
        if target in cls._TERMINAL_PRODUCTION_ONLY and environment is not None:
            env = getattr(environment, 'value', str(environment))
            if env != 'PRODUCTION':
                raise InvalidIntegrationTransitionError(
                    current, target,
                    f'Only a PRODUCTION integration may become PRODUCTION_ACTIVE (environment is {env})')

    @classmethod
    def allowed_next(cls, current):
        return sorted((s for s in cls._ALLOWED.get(_status(current), set())), key=_v)

    @classmethod
    def is_dispatchable(cls, status):
        """Statuses from which any dispatch attempt may proceed to further checks."""
        return _status(status) not in {S.DRAFT, S.SUSPENDED, S.EXPIRED, S.REVOKED}


def _status(value):
    return value if isinstance(value, S) else S(getattr(value, 'value', value))

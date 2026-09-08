"""Verify a recorded human decision; never infer that legal authority exists."""
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.domain.enums import AuthorityType


class AuthorizationValidationError(ValueError):
    pass


class AuthorizationValidator:
    @staticmethod
    def validate_authorization(request, authorization, current_hash):
        auth = authorization
        if not auth or auth.is_invalidated:
            raise AuthorizationValidationError('Authorization is absent or invalidated')
        if not auth.approver_id or not auth.approver_role:
            raise AuthorizationValidationError('Human approver identity is required')
        auth_type = auth.authority_type if isinstance(auth.authority_type, AuthorityType) else (AuthorityType(auth.authority_type) if isinstance(auth.authority_type, str) else None)
        if not auth_type or not auth.authority_reference.strip():
            raise AuthorizationValidationError('Authority type and reference are required')
        if not auth.issuing_authority.strip() or not auth.approved_scope_summary.strip():
            raise AuthorizationValidationError('Issuing authority and explicit scope decision are required')
        if (auth.bound_canonical_hash != current_hash or auth.bound_request_version != request.request_version
                or auth.approved_scope != request.canonical_dict()):
            raise AuthorizationValidationError('Authorization does not bind to this exact request version and scope')
        for value in (auth.valid_from, auth.valid_until, auth.authorized_at):
            if value is not None and (value.tzinfo is None or value.utcoffset() is None):
                raise AuthorizationValidationError('Authorization timestamps must include a timezone')
        now = utc_now()
        if not auth.valid_from or auth.valid_from > now:
            raise AuthorizationValidationError('Authorization is not yet valid')
        if auth.valid_until and (auth.valid_until <= now or auth.valid_until <= auth.valid_from):
            raise AuthorizationValidationError('Authorization has expired or its interval is invalid')

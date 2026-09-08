"""Human approval and signing of a stored, immutable request version."""
from copy import deepcopy
from dfap.ldrm_subsystem.domain.models import RequestAuthorization
from dfap.ldrm_subsystem.domain.enums import RequestStatus
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.integration.auth_adapter import DigitalSignature
from dfap.ldrm_subsystem.policy.authorization_validator import AuthorizationValidator
from dfap.ldrm_subsystem.policy.state_machine import RequestStateMachine, transition
from dfap.ldrm_subsystem.persistence.repositories import ConflictError
from dfap.ldrm_subsystem.services.package_service import PackageService


class AuthorizationServiceError(PermissionError):
    pass


class AuthorizationService:
    def __init__(self, access, repository, audit):
        self.access, self.repository, self.audit = access, repository, audit

    def authorize_request(self, request, approver_id, authority_type, authority_reference,
                          issuing_authority, approved_scope_summary, *, expected_version,
                          expected_hash, valid_from=None, valid_until=None):
        user = self.access.require(approver_id, 'AUTHORIZE_REQUEST', request)
        if not user.is_human or not self.access.auth.verify_legal_authority_role(approver_id):
            raise AuthorizationServiceError('Approver lacks designated human authority')
        RequestStateMachine.validate_transition(request.status, RequestStatus.AUTHORIZED)
        package = self.repository.get_package(request.id, request.request_version)
        if expected_version != request.request_version or expected_hash != package.sha256_hash:
            raise ConflictError('Approval is stale; review the current request package')
        if not PackageService.verify_package_hash(request, package.sha256_hash):
            raise ValueError('Request differs from its immutable package')
        from dfap.ldrm_subsystem.domain.enums import AuthorityType
        if isinstance(authority_type, str):
            authority_type = AuthorityType(authority_type)
        auth = RequestAuthorization(
            approver_id=user.user_id, approver_name=user.username, approver_role=user.role,
            authority_type=authority_type, authority_reference=authority_reference,
            issuing_authority=issuing_authority, approved_scope_summary=approved_scope_summary,
            approved_scope=deepcopy(package.canonical_dict), bound_request_version=package.request_version,
            bound_canonical_hash=package.sha256_hash, valid_from=valid_from or utc_now(), valid_until=valid_until)
        AuthorizationValidator.validate_authorization(request, auth, package.sha256_hash)
        request.authorization = auth
        self.repository.record_request_version(request.id, package.request_version,
                                               package.sha256_hash, approver_id,
                                               request.created_at, auth.id)
        self.repository.put('authorization_decision', auth.id, auth, request.id, immutable=True)
        self.repository.put('authorization', auth.id, auth, request.id)
        transition(request, RequestStatus.AUTHORIZED, approver_id, self.audit)
        self.audit.log_event('REQUEST_AUTHORIZED', 'LawfulDataRequest', request.id, approver_id,
                             {'authorization_id': auth.id, 'version': package.request_version, 'hash': package.sha256_hash})
        return auth

    def validate_current(self, request, *, signed=False):
        package = self.repository.get_package(request.id, request.request_version)
        if not PackageService.verify_package_hash(request, package.sha256_hash) or request.canonical_hash != package.sha256_hash:
            raise ValueError('Request package hash mismatch')
        auth = request.authorization
        AuthorizationValidator.validate_authorization(request, auth, package.sha256_hash)
        recorded = self.repository.get('authorization', auth.id, RequestAuthorization)
        if recorded != auth:
            raise ValueError('Authorization record mismatch')
        self.access.require(auth.approver_id, 'AUTHORIZE_REQUEST', request)
        if not self.access.auth.verify_legal_authority_role(auth.approver_id):
            raise AuthorizationServiceError('Approver designation has been revoked')
        if signed:
            self.access.require(auth.signer_id, 'SIGN_REQUEST', request)
            if not auth.digital_signature or not self.access.auth.verify_signature(DigitalSignature(
                    auth.signature_algorithm, auth.digital_signature, auth.signer_id, package.sha256_hash)):
                raise ValueError('Invalid package signature')
        return package

    def sign_request(self, request, signer_id, *, expected_hash):
        self.access.require(signer_id, 'SIGN_REQUEST', request)
        RequestStateMachine.validate_transition(request.status, RequestStatus.SIGNED)
        package = self.validate_current(request)
        if expected_hash != package.sha256_hash:
            raise ConflictError('Signing request is stale')
        signature = self.access.auth.sign_hash(signer_id, package.sha256_hash)
        if signature.signer_id != signer_id or signature.signed_hash != package.sha256_hash or not self.access.auth.verify_signature(signature):
            raise ValueError('Signing service returned an invalid signature')
        auth = request.authorization
        auth.digital_signature, auth.signer_id, auth.signature_algorithm = signature.signature_hex, signer_id, signature.signature_algorithm
        self.repository.put('authorization', auth.id, auth, request.id)
        self.repository.put('signature', auth.id, signature, request.id, immutable=True)
        transition(request, RequestStatus.SIGNED, signer_id, self.audit)
        self.audit.log_event('REQUEST_SIGNED', 'LawfulDataRequest', request.id, signer_id, {'hash': package.sha256_hash})
        return request

    def invalidate(self, request, actor_id, reason):
        if request.authorization and not request.authorization.is_invalidated:
            request.authorization.invalidate(reason)
            request.authorization.digital_signature = ''
            self.repository.put('authorization', request.authorization.id, request.authorization, request.id)
            self.audit.log_event('AUTHORIZATION_INVALIDATED', 'LawfulDataRequest', request.id, actor_id,
                                 {'reason': reason, 'authorization_id': request.authorization.id})

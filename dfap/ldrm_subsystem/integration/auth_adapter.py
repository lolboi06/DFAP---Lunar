"""
Auth Adapter Interface and Implementation for DFAP Authentication & RBAC.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, Any, Set
import hashlib
import hmac
import secrets
from copy import deepcopy

@dataclass
class UserContext:
    user_id: str
    username: str
    role: str
    permissions: Set[str]
    is_human: bool = False
    designated_approver: bool = False


@dataclass
class DigitalSignature:
    signature_algorithm: str
    signature_hex: str
    signer_id: str
    signed_hash: str


class AuthAdapter(ABC):
    """Abstract interface to DFAP Authentication and RBAC subsystem."""

    @abstractmethod
    def get_user_by_id(self, user_id: str) -> Optional[UserContext]:
        """Fetch user by ID."""
        pass

    @abstractmethod
    def verify_permission(self, user_id: str, permission: str) -> bool:
        """Check if user holds a specific system permission."""
        pass

    @abstractmethod
    def verify_legal_authority_role(self, user_id: str) -> bool:
        """Verify user is authorized to grant formal legal approvals."""
        pass

    @abstractmethod
    def sign_hash(self, user_id: str, payload_hash: str) -> DigitalSignature:
        """Generate a cryptographic digital signature for a canonical package hash."""
        pass

    def authenticate(self, credential: str) -> Optional[UserContext]:
        """Verify a host-issued credential. No default identity is permitted."""
        return None

    @abstractmethod
    def verify_signature(self, signature: DigitalSignature) -> bool:
        """Verify using the host signing service and recorded signer/key metadata."""
        raise NotImplementedError


class MockAuthAdapter(AuthAdapter):
    """
    Explicit development/test identity adapter. HMAC is a mock attestation, not a human certificate.
    """

    def __init__(self, tokens=None, signing_key=None):
        self._tokens = tokens or {}
        self._signing_key = signing_key or secrets.token_bytes(32)
        self._users: Dict[str, UserContext] = {
            "inv-001": UserContext(
                user_id="inv-001",
                username="investigator.sharma",
                role="INVESTIGATOR",
                permissions={"CREATE_REQUEST", "VIEW_REQUEST", "EDIT_DRAFT", "SUBMIT_REQUEST"},
            ),
            "inv-002": UserContext(
                user_id="inv-002",
                username="investigator.patel",
                role="INVESTIGATOR",
                permissions={"CREATE_REQUEST", "VIEW_REQUEST", "EDIT_DRAFT", "SUBMIT_REQUEST"},
            ),
            "legal-001": UserContext(
                user_id="legal-001",
                username="legal.advocate.verma",
                role="LEGAL_OFFICER",
                permissions={"VIEW_REQUEST", "REVIEW_LEGAL", "AUTHORIZE_REQUEST", "SIGN_REQUEST"},
            ),
            "sup-001": UserContext(
                user_id="sup-001",
                username="supervisor.menon",
                role="SUPERVISOR",
                permissions={"VIEW_REQUEST", "AUTHORIZE_REQUEST", "DISPATCH_REQUEST", "SIGN_REQUEST"},
            ),
            "admin-001": UserContext(
                user_id="admin-001",
                username="admin.sys",
                role="ADMIN",
                permissions={
                    "CREATE_REQUEST", "VIEW_REQUEST", "EDIT_DRAFT", "SUBMIT_REQUEST",
                    "REVIEW_LEGAL", "AUTHORIZE_REQUEST", "SIGN_REQUEST", "DISPATCH_REQUEST",
                    "MANAGE_PROVIDERS", "SYSTEM_AUDIT",
                },
            ),
        }

        for user in self._users.values():
            user.is_human = True
            user.designated_approver = user.role in {"LEGAL_OFFICER", "SUPERVISOR"}
            if user.role in {"INVESTIGATOR", "SUPERVISOR", "ADMIN"}:
                user.permissions.update({"RECEIVE_RESPONSE", "VERIFY_EVIDENCE", "INGEST_DATASET", "CLOSE_REQUEST", "CANCEL_REQUEST", "PROVIDER_QUERY", "EXPIRE_REQUEST"})

    def authenticate(self, credential):
        for token, user_id in self._tokens.items():
            if hmac.compare_digest(token.encode('utf-8'), credential.encode('utf-8')):
                return self.get_user_by_id(user_id)
        return None

    def verify_signature(self, signature):
        if signature.signature_algorithm != "HMAC-SHA256":
            return False
        expected = hmac.new(self._signing_key, f"{signature.signer_id}:{signature.signed_hash}".encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.signature_hex)

    def get_user_by_id(self, user_id: str) -> Optional[UserContext]:
        return deepcopy(self._users.get(user_id))

    def verify_permission(self, user_id: str, permission: str) -> bool:
        user = self.get_user_by_id(user_id)
        if not user:
            return False
        return permission in user.permissions

    def verify_legal_authority_role(self, user_id: str) -> bool:
        user = self.get_user_by_id(user_id)
        if not user:
            return False
        return user.is_human and user.designated_approver

    def sign_hash(self, user_id: str, payload_hash: str) -> DigitalSignature:
        user = self.get_user_by_id(user_id)
        if not user or not self.verify_permission(user_id, "SIGN_REQUEST"):
            raise PermissionError(f"Unknown or unauthorized user ID: '{user_id}' cannot sign hash.")
        
        sig = hmac.new(
            self._signing_key,
            f"{user_id}:{payload_hash}".encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        return DigitalSignature(
            signature_algorithm="HMAC-SHA256",
            signature_hex=sig,
            signer_id=user_id,
            signed_hash=payload_hash,
        )

# Compatibility name; this is explicitly a test double, never production identity.
DefaultAuthAdapter = MockAuthAdapter

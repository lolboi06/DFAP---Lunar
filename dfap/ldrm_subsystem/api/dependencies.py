"""Verify host credentials; never trust a caller-supplied actor header or body."""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

bearer = HTTPBearer(auto_error=False)


def get_module(request: Request):
    return request.app.state.ldrm


def get_request_service(module=Depends(get_module)):
    return module.service


def get_advisory_service(module=Depends(get_module)):
    return module.advisory_service


def get_clarification_service(module=Depends(get_module)):
    return module.clarification_service


def get_actor(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), module=Depends(get_module)):
    user = module.auth_adapter.authenticate(credentials.credentials) if credentials else None
    if user is None:
        module.audit_adapter.log_security_violation('Invalid or missing authentication', 'anonymous')
        raise HTTPException(401, 'Authentication required', headers={'WWW-Authenticate': 'Bearer'})
    return user.user_id


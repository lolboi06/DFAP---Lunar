"""Action and case authorization apply to services as well as HTTP callers."""

class AccessDenied(PermissionError):
    def __init__(self, actor_id, permission, case_id=None, request_id=None):
        super().__init__(f'Actor lacks permission: {permission}')
        self.actor_id = actor_id
        self.context = {'permission': permission, 'case_id': case_id, 'target_id': request_id or case_id or 'GLOBAL'}


class AccessPolicy:
    def __init__(self, auth, cases):
        self.auth = auth
        self.cases = cases

    def require(self, actor_id, permission, request=None, case_id=None, active=True):
        case_id = request.case_id if request else case_id
        if request and permission in {'AUTHORIZE_REQUEST', 'SIGN_REQUEST'} and request.created_by == actor_id:
            raise AccessDenied(actor_id, f"{permission}_SEPARATION_OF_DUTIES (Separation of duties: creator cannot authorize or sign)", case_id, request.id)
        user = self.auth.get_user_by_id(actor_id)
        allowed = user and self.auth.verify_permission(actor_id, permission)
        if case_id:
            allowed = allowed and self.cases.user_has_case_access(actor_id, case_id, permission)
            if active:
                allowed = allowed and self.cases.validate_case_active(case_id)
        if not allowed:
            raise AccessDenied(actor_id, permission, case_id, request.id if request else None)
        return user

    def administrator(self, actor_id):
        user = self.require(actor_id, 'MANAGE_PROVIDERS', active=False)
        if user.role != 'ADMIN':
            raise AccessDenied(actor_id, 'MANAGE_PROVIDERS')
        return user

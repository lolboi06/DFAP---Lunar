"""Console integration for an authenticated host session; no default identities."""
from dfap.ldrm_subsystem.domain.models import RequestTarget
from dfap.ldrm_subsystem.domain.enums import DatasetType, TargetType, AuthorityType


class LDRMConsoleCLI:
    def __init__(self, request_service, actor_id):
        self.service, self.actor_id = request_service, actor_id

    def cmd_list_providers(self):
        return '\n'.join(f'{p.id} | {p.name} | {p.verification_status.value}'
                         for p in self.service.provider_registry.list_providers(self.actor_id))

    def cmd_create_request(self, case_id, provider_id, dataset_type_str, target_type_str,
                           target_value, *, start_time, end_time, categories, justification):
        target = RequestTarget(target_type=TargetType(target_type_str.upper()), target_value=target_value,
                               start_time=start_time, end_time=end_time, requested_categories=categories, justification=justification)
        request = self.service.create_request(case_id, provider_id, DatasetType(dataset_type_str.upper()), [target], self.actor_id)
        return f'Created Request: {request.request_number} (ID: {request.id})'

    def cmd_authorize(self, request_id, *, authority_type, authority_reference, issuing_authority,
                      approved_scope_summary, expected_version, expected_hash):
        return self.service.authorize_request(request_id, self.actor_id, AuthorityType(authority_type),
                    authority_reference, issuing_authority, approved_scope_summary,
                    expected_version=expected_version, expected_hash=expected_hash)

    def cmd_sign_and_dispatch(self, request_id, *, expected_hash):
        self.service.sign_request(request_id, self.actor_id, expected_hash=expected_hash)
        return self.service.dispatch_request(request_id, self.actor_id)

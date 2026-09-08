"""Administrator-managed provider records. No discovery or automatic verification."""
from copy import deepcopy
from dfap.ldrm_subsystem.domain.provider import Provider
from dfap.ldrm_subsystem.domain.enums import TransmissionMethod
from dfap.ldrm_subsystem.domain.enums import ProviderVerificationStatus, ProviderActiveStatus
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.unit_of_work import atomic


class ProviderRegistryError(ValueError):
    pass


class ProviderRegistry:
    def __init__(self, repository, access, audit):
        self.repository, self.access, self.audit_adapter = repository, access, audit

    def _get(self, provider_id):
        return self.repository.get('provider', provider_id, Provider)

    def get_provider(self, provider_id, actor_id):
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        return self._get(provider_id)

    def list_providers(self, actor_id, category=None, only_eligible=False):
        self.access.require(actor_id, 'VIEW_REQUEST', active=False)
        return sorted([p for p in self.repository.list('provider', Provider)
                       if (category is None or p.category == category) and (not only_eligible or p.is_eligible_for_dispatch)], key=lambda p: p.name)

    @atomic
    def register_provider(self, provider, actor_id):
        self.access.administrator(actor_id)
        if not provider.name.strip() or not provider.supported_datasets:
            raise ProviderRegistryError('Provider name and supported datasets are required')
        existing = self.repository.list('provider', Provider)
        if any(p.id == provider.id or p.name.casefold() == provider.name.casefold() for p in existing):
            raise ProviderRegistryError('Provider already exists')
        provider = deepcopy(provider)
        provider.verification_status = ProviderVerificationStatus.PENDING_VERIFICATION
        provider.verified_by = provider.verified_at = provider.verification_notes = None
        self._validate_configuration(provider)
        for destination in provider.destinations:
            destination.verified_by = destination.verified_at = None
        self.repository.put('provider', provider.id, provider)
        self.audit_adapter.log_event('PROVIDER_REGISTERED', 'Provider', provider.id, actor_id)
        return provider

    @atomic
    def update_provider(self, provider_id, actor_id, *, name=None, category=None, supported_datasets=None, contact_details=None, active_status=None, submission_methods=None, response_methods=None,
                        destinations=None, endpoint_references=None, required_documents=None, configuration_metadata=None):
        self.access.administrator(actor_id)
        provider = self._get(provider_id)
        verification_changed = False
        for key, value in {'name': name, 'category': category, 'supported_datasets': supported_datasets, 'contact_details': contact_details, 'submission_methods': submission_methods, 'response_methods': response_methods,
                           'destinations': destinations, 'endpoint_references': endpoint_references,
                           'required_documents': required_documents, 'configuration_metadata': configuration_metadata}.items():
            if value is not None and value != getattr(provider, key):
                setattr(provider, key, deepcopy(value))
                verification_changed = True
        if not provider.name.strip() or not provider.supported_datasets:
            raise ProviderRegistryError('Provider name and supported datasets are required')
        if any(p.id != provider.id and p.name.casefold() == provider.name.casefold() for p in self.repository.list('provider', Provider)):
            raise ProviderRegistryError('Provider name already exists')
        self._validate_configuration(provider)
        if destinations is not None:
            for destination in provider.destinations:
                destination.verified_by = destination.verified_at = None
        if verification_changed:
            provider.verification_status = ProviderVerificationStatus.PENDING_VERIFICATION
            provider.verified_by = provider.verified_at = None
        if active_status is not None:
            provider.active_status = ProviderActiveStatus(active_status)
        provider.updated_at = utc_now()
        self.repository.put('provider', provider.id, provider)
        self.audit_adapter.log_event('PROVIDER_UPDATED', 'Provider', provider.id, actor_id, {'verification_invalidated': verification_changed})
        return provider

    @atomic
    def verify_provider(self, provider_id, verified_by, notes=None):
        self.access.administrator(verified_by)
        provider = self._get(provider_id)
        provider.verify(verified_by, notes)
        self.repository.put('provider', provider.id, provider)
        self.audit_adapter.log_event('PROVIDER_VERIFIED', 'Provider', provider.id, verified_by, provider.to_dict())
        return provider

    @atomic
    def suspend_provider(self, provider_id, actor_id, notes=None):
        self.access.administrator(actor_id)
        provider = self._get(provider_id)
        provider.suspend(notes)
        self.repository.put('provider', provider.id, provider)
        self.audit_adapter.log_event('PROVIDER_SUSPENDED', 'Provider', provider.id, actor_id, {'notes': notes})
        return provider

    def validate_provider_for_dispatch(self, provider_id, dataset_type):
        provider = self._get(provider_id)
        if not provider.is_eligible_for_dispatch:
            raise ProviderRegistryError('Only VERIFIED and ACTIVE providers can receive requests')
        if dataset_type not in provider.supported_datasets:
            raise ProviderRegistryError('Provider does not support the requested dataset')
        return provider


    @staticmethod
    def _validate_configuration(provider):
        supported = set(TransmissionMethod)
        if not provider.submission_methods or any(m not in supported for m in provider.submission_methods):
            raise ProviderRegistryError('Unsupported submission method')
        if len({d.id for d in provider.destinations}) != len(provider.destinations):
            raise ProviderRegistryError('Destination IDs must be unique')
        for destination in provider.destinations:
            if not destination.id or not destination.address.strip() or destination.method not in provider.submission_methods:
                raise ProviderRegistryError('Destination must belong to a configured submission method')

    @atomic
    def verify_destination(self, provider_id, destination_id, actor_id):
        self.access.administrator(actor_id)
        provider = self._get(provider_id)
        destination = next((d for d in provider.destinations if d.id == destination_id), None)
        if destination is None:
            raise KeyError('Destination not found')
        if destination.method == TransmissionMethod.OFFICIAL_EMAIL:
            from dfap.ldrm_subsystem.providers.connectors.email import validate_test_address
            validate_test_address(destination.address)
        destination.verified_by, destination.verified_at = actor_id, utc_now()
        self.repository.put('provider', provider.id, provider)
        self.audit_adapter.log_event('PROVIDER_DESTINATION_VERIFIED', 'Provider', provider.id, actor_id,
                                    {'destination_id': destination.id, 'method': destination.method.value})
        return provider

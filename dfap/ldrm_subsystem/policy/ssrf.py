"""SSRF protection and endpoint allowlisting (Stage 3 §15, §16).

Endpoint identity is administrator-verified configuration, never request input.
Request creators cannot supply a provider URL: this module is the only place an
outbound destination is resolved, and it refuses anything an administrator has
not verified for that exact provider and environment.
"""
import ipaddress
import socket
from urllib.parse import urlparse
from typing import Optional, List, Iterable
from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment
from dfap.ldrm_subsystem.domain.profile import EndpointAllowlistEntry


class SSRFProtectionError(ValueError):
    pass


def _env(value):
    return getattr(value, 'value', str(value))


class SSRFProtection:
    #: Everything except http/https is refused; these are named for clearer errors.
    BLOCKED_SCHEMES = {'file', 'gopher', 'ftp', 'tftp', 'ldap', 'ldaps', 'dict',
                       'jar', 'netdoc', 'mailto', 'data', 'sftp', 'ssh', 'telnet'}
    ALLOWED_SCHEMES = {'http', 'https'}

    #: Cloud instance metadata services across providers.
    METADATA_HOSTS = {'169.254.169.254', 'fd00:ec2::254', 'metadata.google.internal',
                      'metadata.goog', 'metadata', '100.100.100.200'}

    #: IANA-reserved names that can never resolve on the public internet. Safe
    #: for MOCK and SANDBOX; never a PRODUCTION destination.
    RESERVED_SUFFIXES = ('.test', '.example', '.invalid')
    #: Names that address the host or its private network. Never permitted
    #: outside MOCK, where the transport is in-process and has no socket at all.
    LOCAL_SUFFIXES = ('.local', '.localhost', '.internal', '.home.arpa')
    LOCAL_HOSTS = {'localhost', '127.0.0.1', '::1', '0.0.0.0', '[::1]'}

    #: Environments that require an administrator-verified allowlist entry.
    ALLOWLIST_REQUIRED = {IntegrationEnvironment.SANDBOX.value, IntegrationEnvironment.PRODUCTION.value}

    @classmethod
    def validate_transport_rules(cls, url: str, environment: IntegrationEnvironment,
                                 resolve_dns: bool = False) -> str:
        """Scheme, host and address rules only, without the allowlist requirement.

        Used where a destination is being *recorded* rather than *used*: the
        allowlist is a separate administrator act, and demanding it here would
        report the wrong problem. Never call this in place of
        `validate_endpoint` on a dispatch path.
        """
        return cls._validate(url, environment, allowlist=None, provider_id=None,
                             resolve_dns=resolve_dns, require_allowlist=False)

    @classmethod
    def validate_endpoint(cls, url: str, environment: IntegrationEnvironment,
                          allowlist: Optional[List[EndpointAllowlistEntry]] = None,
                          provider_id: Optional[str] = None,
                          resolve_dns: bool = False) -> str:
        return cls._validate(url, environment, allowlist, provider_id, resolve_dns,
                             require_allowlist=True)

    @classmethod
    def _validate(cls, url: str, environment: IntegrationEnvironment,
                  allowlist: Optional[List[EndpointAllowlistEntry]],
                  provider_id: Optional[str], resolve_dns: bool,
                  require_allowlist: bool) -> str:
        if not url or not str(url).strip():
            raise SSRFProtectionError('Endpoint URL cannot be empty')
        url = str(url).strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in url):
            raise SSRFProtectionError('Endpoint URL contains control characters')

        parsed = urlparse(url)
        scheme = (parsed.scheme or '').lower()
        if scheme in cls.BLOCKED_SCHEMES or scheme not in cls.ALLOWED_SCHEMES:
            raise SSRFProtectionError(f"Prohibited or unsafe URL scheme: '{scheme}'")

        # Credentials in the URL smuggle authority past the allowlist comparison.
        if parsed.username or parsed.password or '@' in (parsed.netloc.split(']')[-1]):
            raise SSRFProtectionError('Credentials embedded in an endpoint URL are not permitted')

        host = (parsed.hostname or '').lower()
        if not host:
            raise SSRFProtectionError('Invalid URL hostname')

        env_val = _env(environment)

        if host in cls.METADATA_HOSTS:
            raise SSRFProtectionError(
                f"Access to cloud metadata endpoint ({host}) is forbidden")

        is_local_name = host in cls.LOCAL_HOSTS or host.endswith(cls.LOCAL_SUFFIXES)
        is_reserved_name = host.endswith(cls.RESERVED_SUFFIXES)

        if env_val == IntegrationEnvironment.MOCK.value:
            # MOCK may only ever address the host itself or a reserved test name.
            if not (is_local_name or is_reserved_name or cls._is_loopback(host)):
                raise SSRFProtectionError(
                    'MOCK integrations may only address localhost or reserved .test destinations')
        elif env_val == IntegrationEnvironment.SANDBOX.value:
            # A sandbox may use a reserved test name or a real non-production
            # host, but never the loopback interface or a private network.
            if is_local_name:
                raise SSRFProtectionError(
                    f'Local/test destinations are strictly forbidden in {env_val} mode')
            cls._reject_internal_address(host, env_val)
            if resolve_dns and not is_reserved_name:
                cls._reject_resolved_internal_addresses(host, env_val)
        else:
            # PRODUCTION: a real, public, https destination only.
            if is_local_name or is_reserved_name:
                raise SSRFProtectionError(
                    f'Local/test destinations are strictly forbidden in {env_val} mode')
            cls._reject_internal_address(host, env_val)
            if scheme != 'https':
                raise SSRFProtectionError('PRODUCTION endpoints must use https; protocol downgrade refused')
            if resolve_dns:
                cls._reject_resolved_internal_addresses(host, env_val)

        # An administrator-verified allowlist entry is mandatory outside MOCK.
        if require_allowlist and allowlist is None and env_val in cls.ALLOWLIST_REQUIRED:
            raise SSRFProtectionError(
                f'No administrator-verified endpoint allowlist is configured for {env_val}; '
                'dispatch fails closed')
        if allowlist is not None:
            active = [entry.url for entry in allowlist
                      if entry.is_active and _env(entry.environment) == env_val
                      and (not provider_id or entry.provider_id == provider_id)]
            if not any(cls._url_matches(url, allowed) for allowed in active):
                raise SSRFProtectionError(
                    f"Endpoint URL '{url}' is not present in the verified administrator "
                    f"allowlist for provider '{provider_id}' ({env_val})")
        return url

    @staticmethod
    def _is_loopback(host: str) -> bool:
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    @classmethod
    def _reject_internal_address(cls, host: str, env_val: str) -> None:
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return  # A name; resolution is handled separately and the allowlist still applies.
        cls._assert_public(ip, host, env_val)

    @staticmethod
    def _assert_public(ip, host: str, env_val: str) -> None:
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
                or ip.is_reserved or ip.is_unspecified):
            raise SSRFProtectionError(
                f"Private/internal IP range '{host}' is forbidden in {env_val} mode")
        # IPv4-mapped and 6to4 addresses can wrap a private v4 address.
        mapped = getattr(ip, 'ipv4_mapped', None) or getattr(ip, 'sixtofour', None)
        if mapped is not None and (mapped.is_private or mapped.is_loopback or mapped.is_link_local):
            raise SSRFProtectionError(
                f"Embedded private IPv4 address in '{host}' is forbidden in {env_val} mode")

    @classmethod
    def _reject_resolved_internal_addresses(cls, host: str, env_val: str) -> None:
        """Best-effort DNS-rebinding defence: every A/AAAA answer must be public.

        Only performed when a caller explicitly opts in. Name resolution is not
        attempted anywhere in the MOCK path, which has no socket access at all.
        """
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError as error:
            raise SSRFProtectionError(f"Endpoint host '{host}' could not be resolved") from error
        for info in infos:
            cls._assert_public(ipaddress.ip_address(info[4][0]), host, env_val)

    @classmethod
    def validate_redirect(cls, original: str, location: str, environment, allowlist=None, provider_id=None) -> str:
        """A redirect target must independently satisfy every endpoint rule."""
        if not location:
            raise SSRFProtectionError('Empty redirect location')
        return cls.validate_endpoint(location, environment, allowlist=allowlist, provider_id=provider_id)

    @staticmethod
    def _url_matches(target: str, allowed: str) -> bool:
        t, a = urlparse(target), urlparse(allowed)
        if t.scheme != a.scheme or t.hostname != a.hostname or t.port != a.port:
            return False
        base = a.path.rstrip('/')
        return t.path == a.path or not base or t.path.startswith(base + '/')

    @classmethod
    def assert_no_caller_supplied_endpoint(cls, payload: Iterable) -> None:
        """Refuse any request payload that tries to carry its own destination.

        Endpoint identity lives in the provider integration profile. A request
        creator, an API client or a generated suggestion cannot introduce one.
        """
        forbidden = {'endpoint', 'endpoint_reference', 'url', 'destination', 'callback_url',
                     'base_url', 'host', 'webhook_url', 'target_url'}
        present = sorted(forbidden.intersection(set(payload or ())))
        if present:
            raise SSRFProtectionError(
                'Request input may not specify a provider destination; endpoint identity is '
                f'administrator-verified configuration (rejected fields: {", ".join(present)})')

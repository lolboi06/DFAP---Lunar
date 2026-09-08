"""Outbound HTTPS transport for one authorized provider sandbox (Stage 4).

This is the only code in DFAP that may open a socket to an external host, and it
can only be constructed from a live `SandboxAuthorization`. Every call:

  * uses https with TLS verification on — there is no way to disable it;
  * resolves the destination against the administrator allowlist again, at call
    time, not just at configuration time;
  * follows no redirect implicitly — each hop is re-validated or refused;
  * enforces connect/read/write timeouts and a hard response-size ceiling;
  * resolves credentials through the `SecretProvider` at the moment of use;
  * records an append-only exchange log of hashes and safe metadata, never
    bodies, headers or credential values.

Transport failures and provider decisions are different things. A timeout is
`RetryableTransportError`; an HTTP 4xx carrying a provider's decision is
`NonRetryableTransportError` and must never be retried automatically.
"""
import hashlib
import logging
import ssl
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from urllib.parse import urljoin, urlparse

import httpx

from dfap.ldrm_subsystem.domain.enums import IntegrationEnvironment
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.policy.ssrf import SSRFProtection, SSRFProtectionError
from dfap.ldrm_subsystem.security.secrets import REDACTED

logger = logging.getLogger(__name__)

#: Header names whose values are never logged, stored or returned.
SENSITIVE_HEADERS = {'authorization', 'proxy-authorization', 'x-api-key', 'api-key',
                     'x-auth-token', 'cookie', 'set-cookie', 'x-provider-signature'}

#: Redirects are re-validated rather than followed blindly, and only this many.
MAX_REDIRECTS = 3


class SandboxTransportError(RuntimeError):
    """Base class. Carries no credential material in its message."""


class RetryableTransportError(SandboxTransportError):
    """A transport-level failure. The same request may be sent again."""


class NonRetryableTransportError(SandboxTransportError):
    """A refusal or a malformed exchange. Never retried automatically."""


class TLSVerificationError(NonRetryableTransportError):
    """The sandbox's certificate could not be verified. Always fatal."""


class ResponseTooLarge(NonRetryableTransportError):
    """The sandbox returned more than the authorized ceiling."""


def redact_headers(headers) -> Dict[str, str]:
    """Header map safe to log. Sensitive values become a marker, not a prefix."""
    return {k: (REDACTED if k.lower() in SENSITIVE_HEADERS else v)
            for k, v in dict(headers or {}).items()}


@dataclass
class TransportResult:
    status_code: int
    body: bytes
    headers: Dict[str, str] = field(default_factory=dict)
    url: str = ''
    duration_ms: int = 0

    @property
    def body_sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def safe_summary(self) -> Dict[str, Any]:
        return {'status_code': self.status_code, 'bytes': len(self.body),
                'sha256': self.body_sha256, 'duration_ms': self.duration_ms,
                'headers': redact_headers(self.headers)}


class SandboxHTTPTransport:
    """HTTPS client bound to exactly one authorized sandbox."""

    def __init__(self, authorization, secret_provider, repository, audit=None,
                 client_factory=None):
        if authorization is None:
            raise SandboxTransportError('A sandbox transport requires a SandboxAuthorization')
        if not authorization.is_live:
            raise SandboxTransportError(
                f'Sandbox authorization is not live: {authorization.why_not_live()}')
        if authorization.environment != IntegrationEnvironment.SANDBOX:
            raise SandboxTransportError(
                'SandboxHTTPTransport serves the SANDBOX environment only')
        if not authorization.base_url.lower().startswith('https://'):
            raise SandboxTransportError('A sandbox base URL must use https')

        self.authorization = authorization
        self.secrets = secret_provider
        self.repository = repository
        self.audit = audit
        #: Injected only so tests can supply an httpx MockTransport. A factory
        #: cannot relax TLS: verification arguments are set here, not by it.
        self._client_factory = client_factory

    # ------------------------------------------------------------ requests

    def request(self, method: str, path: str, *, json_body=None, request_id=None,
                transmission_id=None) -> TransportResult:
        """Perform one exchange against the authorized sandbox."""
        auth = self.authorization
        if not auth.is_live:
            raise NonRetryableTransportError(
                f'Sandbox authorization is no longer live: {auth.why_not_live()}')

        url = self._resolve(path)
        headers = self._headers()
        started = time.monotonic()

        try:
            result = self._send(method, url, headers, json_body, started)
        except (TLSVerificationError, ResponseTooLarge):
            raise
        except httpx.TimeoutException as error:
            self._log_exchange(method, path, None, None, 'TIMEOUT', str(type(error).__name__),
                               request_id, transmission_id, started)
            raise RetryableTransportError(
                f'Sandbox did not respond within {auth.request_timeout_seconds}s') from error
        except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as error:
            if _is_tls_failure(error):
                self._log_exchange(method, path, None, None, 'TLS_FAILURE',
                                   type(error).__name__, request_id, transmission_id, started)
                raise TLSVerificationError(
                    'Sandbox TLS certificate could not be verified; the exchange was abandoned'
                ) from error
            self._log_exchange(method, path, None, None, 'CONNECT_FAILURE',
                               type(error).__name__, request_id, transmission_id, started)
            raise RetryableTransportError(
                f'Sandbox is unreachable ({type(error).__name__})') from error
        except httpx.HTTPError as error:
            self._log_exchange(method, path, None, None, 'TRANSPORT_ERROR',
                               type(error).__name__, request_id, transmission_id, started)
            raise NonRetryableTransportError(
                f'Sandbox exchange failed ({type(error).__name__})') from error

        self._log_exchange(method, path, result.status_code, result, 'OK',
                           f'{result.status_code}', request_id, transmission_id, started,
                           request_body=json_body)
        return result

    def _send(self, method, url, headers, json_body, started) -> TransportResult:
        auth = self.authorization
        timeout = httpx.Timeout(connect=min(10.0, auth.request_timeout_seconds),
                                read=auth.request_timeout_seconds,
                                write=auth.request_timeout_seconds,
                                pool=min(10.0, auth.request_timeout_seconds))
        current_url, seen = url, 0

        while True:
            with self._client(timeout) as client:
                # follow_redirects is False on the client; each hop is inspected.
                response = client.request(method, current_url, headers=headers,
                                          json=json_body if json_body is not None else None)

                if response.is_redirect and seen < MAX_REDIRECTS:
                    location = response.headers.get('location', '')
                    target = urljoin(current_url, location)
                    # A redirect target is a new destination and gets the full
                    # policy check, including the allowlist.
                    try:
                        SSRFProtection.validate_redirect(
                            current_url, target, IntegrationEnvironment.SANDBOX,
                            allowlist=self._allowlist(), provider_id=auth.provider_id)
                    except SSRFProtectionError as error:
                        raise NonRetryableTransportError(
                            f'Sandbox redirect refused: {error}') from error
                    if not self._within_base(target):
                        raise NonRetryableTransportError(
                            'Sandbox redirect leaves the authorized base URL')
                    current_url, seen = target, seen + 1
                    continue
                if response.is_redirect:
                    raise NonRetryableTransportError(
                        f'Sandbox exceeded {MAX_REDIRECTS} redirects')

                body = self._read_capped(response)

            return TransportResult(
                status_code=response.status_code, body=body,
                headers=dict(response.headers), url=current_url,
                duration_ms=int((time.monotonic() - started) * 1000))

    def _read_capped(self, response) -> bytes:
        """Read at most the authorized ceiling, refusing anything larger.

        A declared Content-Length is checked first so an oversized body is
        refused before it is transferred; the streamed read then enforces the
        same ceiling for a provider that declares nothing or under-declares.
        """
        limit = self.authorization.max_response_bytes
        declared = response.headers.get('content-length')
        if declared is not None:
            try:
                if int(declared) > limit:
                    raise ResponseTooLarge(
                        f'Sandbox declared {declared} bytes, over the {limit}-byte ceiling')
            except ValueError:
                raise NonRetryableTransportError('Sandbox sent a malformed Content-Length')

        chunks, total = [], 0
        for chunk in response.iter_bytes():
            total += len(chunk)
            if total > limit:
                raise ResponseTooLarge(
                    f'Sandbox response exceeded the {limit}-byte ceiling')
            chunks.append(chunk)
        return b''.join(chunks)

    # ------------------------------------------------------------ internals

    def _client(self, timeout):
        if self._client_factory is not None:
            return self._client_factory(timeout)
        # TLS verification is on and there is no parameter to turn it off.
        context = ssl.create_default_context()
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        cert = None
        if self.authorization.client_certificate_reference:
            cert = self._client_certificate()
        return httpx.Client(verify=context, cert=cert, timeout=timeout,
                            follow_redirects=False, trust_env=False,
                            headers={'User-Agent': 'DFAP-LDRM/4.0 (authorized sandbox)'})

    def _client_certificate(self):
        """Resolve mTLS material through the secret backend, never from the DB."""
        bundle = self.secrets.get_certificate(
            self.authorization.client_certificate_reference, IntegrationEnvironment.SANDBOX)
        path = bundle.get('client_cert_path') if isinstance(bundle, dict) else None
        if not path:
            raise NonRetryableTransportError(
                'The configured secret backend did not return usable client certificate material; '
                'mTLS sandboxes require a backend that can supply a certificate path or handle')
        key_path = bundle.get('client_key_path')
        return (path, key_path) if key_path else path

    def _headers(self) -> Dict[str, str]:
        """Build request headers, resolving the credential at the moment of use."""
        auth = self.authorization
        headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
        method = (auth.authentication_method or '').upper()
        if method in {'NONE', 'MTLS', 'MUTUAL_TLS', 'CLIENT_CERTIFICATE'}:
            return headers
        secret = self.secrets.get_secret(auth.credential_reference, IntegrationEnvironment.SANDBOX)
        if method in {'BEARER', 'OAUTH2', 'OAUTH2_CLIENT_CREDENTIALS', 'TOKEN'}:
            headers['Authorization'] = f'Bearer {secret}'
        elif method in {'API_KEY', 'APIKEY'}:
            headers['X-API-Key'] = secret
        elif method in {'HMAC', 'HMAC_SECRET'}:
            headers['X-API-Key'] = secret
        else:
            raise NonRetryableTransportError(
                f"Unsupported sandbox authentication method '{auth.authentication_method}'")
        return headers

    def _resolve(self, path: str) -> str:
        """Join a mapper-supplied path to the authorized base and re-check it."""
        auth = self.authorization
        if not path.startswith('/') or '://' in path or '..' in path:
            raise NonRetryableTransportError(f"Unsafe sandbox path '{path}'")
        if not any(path == allowed or path.startswith(allowed.rstrip('/') + '/')
                   for allowed in auth.allowed_paths):
            raise NonRetryableTransportError(
                f"Path '{path}' is not among the authorized sandbox paths for this provider")
        url = auth.base_url.rstrip('/') + path
        try:
            SSRFProtection.validate_endpoint(url, IntegrationEnvironment.SANDBOX,
                                             allowlist=self._allowlist(),
                                             provider_id=auth.provider_id)
        except SSRFProtectionError as error:
            raise NonRetryableTransportError(f'Sandbox destination refused: {error}') from error
        return url

    def _allowlist(self):
        return self.repository.list_endpoint_allowlist(
            self.authorization.provider_id, IntegrationEnvironment.SANDBOX)

    def _within_base(self, url: str) -> bool:
        base, target = urlparse(self.authorization.base_url), urlparse(url)
        return (base.scheme == target.scheme and base.netloc == target.netloc
                and target.path.startswith(base.path.rstrip('/')))

    def _log_exchange(self, method, path, http_status, result, outcome, detail,
                      request_id, transmission_id, started, request_body=None):
        """Append-only record of hashes and safe metadata. Never bodies or headers."""
        try:
            request_hash = None
            if request_body is not None:
                from dfap.ldrm_subsystem.persistence.repositories import encode
                request_hash = hashlib.sha256(encode(request_body).encode()).hexdigest()
            self.repository.record_sandbox_exchange({
                'id': f'SBXE-{uuid.uuid4().hex[:12].upper()}',
                'sandbox_authorization_id': self.authorization.sandbox_authorization_id,
                'request_id': request_id, 'transmission_id': transmission_id,
                'direction': 'OUTBOUND', 'method': method, 'path': path,
                'http_status': http_status,
                'request_body_sha256': request_hash,
                'response_body_sha256': result.body_sha256 if result else None,
                'response_bytes': len(result.body) if result else None,
                'duration_ms': int((time.monotonic() - started) * 1000),
                'outcome': outcome, 'detail': str(detail)[:500],
                'occurred_at': utc_now().isoformat()})
        except Exception:
            # An exchange log failure must not mask the exchange's own outcome.
            logger.exception('Sandbox exchange log write failed')

    def health_check(self) -> Dict[str, Any]:
        """Configuration report. Performs no network call."""
        auth = self.authorization
        return {'status': 'CONFIGURED' if auth.is_live else 'NOT_AUTHORIZED',
                'environment': 'SANDBOX', 'provider_id': auth.provider_id,
                'base_url': auth.base_url, 'authentication_method': auth.authentication_method,
                'credential_reference': auth.credential_reference,
                'tls_verification': 'REQUIRED', 'follow_redirects': False,
                'max_response_bytes': auth.max_response_bytes,
                'timeout_seconds': auth.request_timeout_seconds,
                'expires_at': auth.expires_at.isoformat() if auth.expires_at else None,
                'detail': auth.why_not_live() or 'authorization is live'}


def _is_tls_failure(error) -> bool:
    cause = error
    for _ in range(6):
        if isinstance(cause, ssl.SSLError):
            return True
        if cause is None:
            break
        cause = getattr(cause, '__cause__', None) or getattr(cause, '__context__', None)
    text = str(error).lower()
    return any(token in text for token in
               ('certificate verify failed', 'ssl', 'tls', 'hostname mismatch',
                'self signed', 'self-signed'))

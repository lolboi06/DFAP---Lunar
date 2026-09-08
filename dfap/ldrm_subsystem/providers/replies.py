"""Test reply intake, durable quarantine, and authenticated callback replay protection."""
from abc import ABC, abstractmethod
import base64
import binascii
import csv
import hashlib
import hmac
import io
import json
from datetime import datetime
from pathlib import PurePosixPath
from dfap.ldrm_subsystem.domain.enums import TransmissionMethod, ProviderResponseStatus, RequestStatus
from dfap.ldrm_subsystem.domain.response import ProviderResponse
from dfap.ldrm_subsystem.domain.transmission import RequestTransmission
from dfap.ldrm_subsystem.domain.utils import utc_now
from dfap.ldrm_subsystem.persistence.repositories import encode


class CallbackAuthenticator(ABC):
    @abstractmethod
    def verify(self, provider_id, payload, signature): ...


class TestHMACCallbackAuthenticator(CallbackAuthenticator):
    __test__ = False
    def __init__(self, repository):
        self.repository = repository

    def sign(self, provider_id, payload):
        key = self.repository.get('callback_key', provider_id)['secret']
        return hmac.new(key.encode(), provider_id.encode() + b'\n' + payload, hashlib.sha256).hexdigest()

    def verify(self, provider_id, payload, signature):
        try:
            expected = self.sign(provider_id, payload)
        except KeyError:
            return False
        return hmac.compare_digest(expected.encode(), signature.encode())


class AttachmentValidator:
    """Envelope and file validation (Stage 3 §19).

    Structural safety only. This is not, and does not claim to be, malware
    scanning: `scan_hook` is the integration point where a deployment attaches a
    real scanner, and nothing here executes, renders or interprets provider
    content beyond parsing it as text.
    """

    #: Extensions that must never be accepted from a provider, whatever the
    #: declared media type. Executable and script content has no lawful place
    #: in a dataset response.
    DANGEROUS_EXTENSIONS = {
        '.exe', '.dll', '.so', '.dylib', '.bat', '.cmd', '.com', '.scr', '.msi', '.jar',
        '.sh', '.bash', '.zsh', '.ps1', '.psm1', '.vbs', '.vbe', '.js', '.mjs', '.jse',
        '.wsf', '.wsh', '.hta', '.lnk', '.pif', '.reg', '.py', '.pyc', '.rb', '.pl',
        '.php', '.apk', '.app', '.deb', '.rpm', '.bin', '.elf', '.htm', '.html', '.svg',
        '.xhtml', '.xml', '.xsl', '.xslt',
    }

    #: Media types and extensions a response may use. Anything else is quarantined.
    ALLOWED_TYPES = {
        'application/json': ('.json',),
        'text/csv': ('.csv',),
    }

    #: Archive magic bytes. Archives are refused: they enable zip bombs, nested
    #: archives and path traversal through entry names.
    ARCHIVE_SIGNATURES = (
        (b'PK\x03\x04', 'ZIP'), (b'PK\x05\x06', 'ZIP'), (b'PK\x07\x08', 'ZIP'),
        (b'\x1f\x8b', 'GZIP'), (b'BZh', 'BZIP2'), (b'\xfd7zXZ\x00', 'XZ'),
        (b'7z\xbc\xaf\x27\x1c', '7-ZIP'), (b'Rar!\x1a\x07', 'RAR'),
        (b'\x04\x22\x4d\x18', 'LZ4'), (b'\x28\xb5\x2f\xfd', 'ZSTD'),
        (b'ustar', 'TAR'),
    )

    #: Executable magic bytes.
    EXECUTABLE_SIGNATURES = (
        (b'MZ', 'DOS/PE executable'), (b'\x7fELF', 'ELF executable'),
        (b'\xca\xfe\xba\xbe', 'Mach-O/Java class'), (b'\xcf\xfa\xed\xfe', 'Mach-O'),
        (b'#!', 'script shebang'), (b'%PDF', 'PDF document'),
    )

    MAX_FILENAME_LENGTH = 200

    def __init__(self, scan_hook=None):
        #: Deployment-supplied callable `(raw_bytes, filename) -> Optional[str]`.
        #: Returning a string quarantines the attachment with that reason.
        self.scan_hook = scan_hook

    def safe_storage_name(self, provider_id, event_id, index, filename):
        """Generate the on-disk name. The provider never chooses a path."""
        digest = hashlib.sha256(f'{provider_id}:{event_id}:{index}'.encode()).hexdigest()
        suffix = PurePosixPath(filename).suffix.lower()
        if suffix not in {ext for exts in self.ALLOWED_TYPES.values() for ext in exts}:
            suffix = '.bin'
        return f'{digest}{suffix}'

    def _filename_error(self, name):
        if not name or len(name) > self.MAX_FILENAME_LENGTH:
            return 'Unsafe attachment filename'
        # Reject traversal, absolute paths, separators, control characters,
        # NUL, Windows drive letters, reserved device names, and unicode
        # direction overrides used to disguise an extension.
        if ('/' in name or '\\' in name or '..' in name or name.startswith('.')
                or PurePosixPath(name).name != name
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or any(c in name for c in '\u202e\u202d\u200e\u200f\u2066\u2067')
                or (len(name) > 1 and name[1] == ':')
                or PurePosixPath(name).stem.upper() in {
                    'CON', 'PRN', 'AUX', 'NUL', 'COM1', 'COM2', 'COM3', 'COM4',
                    'LPT1', 'LPT2', 'LPT3'}):
            return 'Unsafe attachment filename'
        suffix = PurePosixPath(name).suffix.lower()
        if suffix in self.DANGEROUS_EXTENSIONS:
            return f'Executable or script attachment type is refused: {suffix}'
        # A double extension hides the real one from a human reader.
        parts = [p for p in name.lower().split('.') if p]
        if len(parts) > 2 and any(f'.{p}' in self.DANGEROUS_EXTENSIONS for p in parts[1:-1]):
            return 'Unsafe attachment filename'
        return None

    def _content_error(self, raw, name, mime):
        for signature, label in self.ARCHIVE_SIGNATURES:
            if raw.startswith(signature) or (label == 'TAR' and raw[257:262] == b'ustar'):
                return (f'Archive attachments are refused ({label}); decompression, nested '
                        'archives and entry-path traversal are outside the validated envelope')
        for signature, label in self.EXECUTABLE_SIGNATURES:
            if raw.startswith(signature):
                return f'Executable or binary attachment is refused ({label})'
        return None

    def validate(self, attachment, max_size):
        try:
            raw = base64.b64decode(attachment['content_base64'], validate=True)
        except (ValueError, binascii.Error):
            return attachment['content_base64'].encode(), 'Malformed base64 attachment'
        name, mime = attachment['filename'], attachment['content_type']

        error = self._filename_error(name)
        if error:
            return raw, error
        if not raw or len(raw) > max_size:
            return raw, 'Attachment is empty or exceeds the configured limit'
        if attachment.get('sha256') and hashlib.sha256(raw).hexdigest() != attachment['sha256']:
            return raw, 'Attachment hash mismatch'

        error = self._content_error(raw, name, mime)
        if error:
            return raw, error

        # The declared media type must match the extension, so a provider cannot
        # label executable content as JSON.
        expected = self.ALLOWED_TYPES.get(mime)
        if expected is None:
            return raw, 'Unsupported attachment type; release requires a production validation policy'
        if PurePosixPath(name).suffix.lower() not in expected:
            return raw, f"Declared type '{mime}' does not match the filename extension"

        try:
            text = raw.decode('utf-8')
            if '\x00' in text:
                return raw, 'NUL bytes are not allowed in text attachments'
            if mime == 'application/json':
                document = json.loads(text, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite JSON')))
                if not isinstance(document, (dict, list)):
                    raise ValueError('JSON attachment must contain an object or array')
            elif mime == 'text/csv':
                rows = csv.reader(io.StringIO(text), strict=True)
                header = next(rows)
                if not header or any(not cell.strip() for cell in header):
                    raise ValueError('CSV header is required')
                if any(len(row) != len(header) for row in rows):
                    raise ValueError('CSV columns are inconsistent')
        except (UnicodeError, ValueError, csv.Error, StopIteration):
            return raw, 'Malformed attachment content'

        if self.scan_hook is not None:
            # Integration point for a deployment's malware scanner. Absence is
            # not a clean result; it means no scan was performed.
            verdict = self.scan_hook(raw, name)
            if verdict:
                return raw, f'Rejected by content scanner: {verdict}'
        return raw, None


class ProviderReplyReceiver:
    def __init__(self, repository, registry, audit, max_size, authenticator=None):
        self.repository, self.registry, self.audit = repository, registry, audit
        self.max_size, self.validator = max_size, AttachmentValidator()
        self.authenticator = authenticator or TestHMACCallbackAuthenticator(repository)

    def accept(self, provider_id, event, actor_id, *, webhook=False, raw_body=None, signature=None):
        if webhook and not self.authenticator.verify(provider_id, raw_body, signature or ''):
            self.audit.log_security_violation('Invalid provider callback signature', 'provider:' + provider_id)
            raise PermissionError('Invalid provider callback signature')
        timestamp = datetime.fromisoformat(event['timestamp'])
        if not timestamp.tzinfo or abs((utc_now() - timestamp).total_seconds()) > 300:
            raise ValueError('Provider event timestamp is outside the five-minute acceptance window')
        payload = encode(event)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.repository.transaction():
            previous = self.repository.connection.execute('SELECT payload_hash,payload FROM communication_events WHERE provider_id=? AND event_id=?',
                                                          (provider_id, event['event_id'])).fetchone()
            if previous:
                if previous['payload_hash'] != digest:
                    raise ValueError('Provider event ID was replayed with different content')
                return {**json.loads(previous['payload'])['result'], 'duplicate': True}
            request = self.repository.get_request(event['request_id'])
            if request.status not in {RequestStatus.SENT, RequestStatus.ACKNOWLEDGED, RequestStatus.RESPONSE_PENDING,
                                      RequestStatus.PROVIDER_QUERY, RequestStatus.PROVIDER_PROCESSING,
                                      RequestStatus.PARTIAL_RESPONSE, RequestStatus.RESPONSE_RECEIVED}:
                raise ValueError('Request is not awaiting provider communications')
            provider = self.registry.validate_provider_for_dispatch(provider_id, request.dataset_type)
            if request.provider_id != provider_id or event['request_reference'] != request.request_number:
                raise ValueError('Provider reply does not identify this request')
            transmissions = self.repository.list('transmission', RequestTransmission, request.id)
            if not transmissions:
                raise ValueError('Unsent requests cannot receive provider replies')
            transmission = transmissions[-1]
            if event['provider_reference'] != transmission.provider_tracking_ref or event['thread_reference'] != transmission.provider_tracking_ref:
                raise ValueError('Provider reply thread/reference mismatch')
            if webhook:
                if transmission.transmission_method != TransmissionMethod.OFFICIAL_API or 'WEBHOOK' not in provider.response_methods:
                    raise ValueError('Callbacks are not configured for this provider/transmission')
            elif transmission.transmission_method == TransmissionMethod.OFFICIAL_EMAIL:
                if 'EMAIL' not in provider.response_methods or event.get('sender') != transmission.metadata.get('recipient'):
                    raise ValueError('Reply sender does not match the verified transmission recipient')
            else:
                raise ValueError('Test email replies require an email transmission')
            status = {'ACKNOWLEDGED': 'ACCEPTED', 'RESPONSE_RECEIVED': 'COMPLETED'}.get(event['status'], event['status'])
            status = ProviderResponseStatus(status)
            attachments = event.get('attachments', [])
            if len(attachments) > 10:
                raise ValueError('At most ten attachments are accepted per event')
            if status in {ProviderResponseStatus.COMPLETED, ProviderResponseStatus.PARTIAL_RESPONSE} and not attachments:
                raise ValueError('A dataset response requires an attachment')
            if status not in {ProviderResponseStatus.COMPLETED, ProviderResponseStatus.PARTIAL_RESPONSE} and attachments:
                raise ValueError('Acknowledgements, queries and rejections cannot contain dataset attachments')
            quarantine_ids, validated, errors = [], [], []
            for index, attachment in enumerate(attachments):
                raw, error = self.validator.validate(attachment, self.max_size)
                qid = hashlib.sha256(f'{provider_id}:{event["event_id"]}:{index}'.encode()).hexdigest()
                metadata = {'provider_id': provider_id, 'event_id': event['event_id'], 'filename': attachment['filename'],
                            'status': 'QUARANTINED' if error else 'VALIDATED', 'error': error,
                            'sha256': hashlib.sha256(raw).hexdigest(), 'received_at': utc_now().isoformat()}
                self.repository.connection.execute('INSERT INTO quarantine VALUES(?,?,?,?)', (qid, request.id, raw, encode(metadata)))
                quarantine_ids.append(qid)
                if error:
                    errors.append(error)
                else:
                    validated.append((qid, raw, metadata))
            result = {'event_id': event['event_id'], 'request_id': request.id, 'status': 'QUARANTINED' if errors else 'QUEUED',
                      'quarantine_ids': quarantine_ids, 'errors': errors, 'duplicate': False}
            self.repository.connection.execute('INSERT INTO communication_events VALUES(?,?,?,?,?)',
                (provider_id, event['event_id'], request.id, digest, encode({'event': event, 'result': result})))
            if not errors:
                channel = self.repository.get('communication_channel', transmission.provider_tracking_ref)
                # Monotonic receipt: an older callback must not undo newer status/data.
                previous_time = channel.get('event_timestamp')
                if previous_time and timestamp < datetime.fromisoformat(previous_time):
                    raise ValueError('Out-of-order provider event')
                if channel['status'] in {'COMPLETED', 'REJECTED'} and channel['status'] != status.value:
                    raise ValueError('A final provider status cannot be reversed')
                channel['status'], channel['event_timestamp'] = status.value, timestamp.isoformat()
                channel['callback_received'] = webhook
                for qid, raw, metadata in validated:
                    response = ProviderResponse(id='reply-' + qid, request_id=request.id, provider_id=provider_id,
                        case_id=request.case_id, transmission_id=transmission.id, provider_status=status,
                        raw_payload=raw, raw_payload_hash=metadata['sha256'], metadata={'tracking_ref': transmission.provider_tracking_ref,
                            'quarantine_id': qid, 'communication_event_id': event['event_id'], 'filename': metadata['filename'],
                            'test_only': True, 'provider_reference': event.get('institution_reference')})
                    channel['responses'].append(json.loads(encode(response)))
                self.repository.put('communication_channel', transmission.provider_tracking_ref, channel, request.id)
            self.audit.log_event('PROVIDER_REPLY_QUARANTINED' if errors else 'PROVIDER_REPLY_QUEUED',
                                 'LawfulDataRequest', request.id, actor_id, result)
            return result

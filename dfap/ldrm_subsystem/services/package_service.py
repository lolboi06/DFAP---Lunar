"""Canonical UTF-8 packages. Stored versions contain immutable bytes."""
import hashlib
import json
from dataclasses import dataclass

@dataclass(frozen=True)
class CanonicalPackage:
    canonical_json: str
    sha256_hash: str
    request_version: int

    @property
    def canonical_dict(self):
        # A detached view cannot alter the packaged bytes.
        return json.loads(self.canonical_json)

class PackageService:
    @staticmethod
    def serialize_canonical(data):
        return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)

    @staticmethod
    def compute_sha256(content):
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def generate_package(cls, request):
        canonical = cls.serialize_canonical(request.canonical_dict())
        return CanonicalPackage(canonical, cls.compute_sha256(canonical), request.request_version)

    @classmethod
    def verify_package_hash(cls, request, expected_hash):
        return cls.generate_package(request).sha256_hash == expected_hash

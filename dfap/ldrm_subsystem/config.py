"""LDRM configuration. Disabled unless explicitly enabled by the application.

Every security-relevant default fails closed: the module is disabled, demo mode
is off, and production dispatch is off. Nothing here infers an environment from
a hostname; the integration environment is persisted per provider integration.
"""
import os
from dataclasses import dataclass, field


def env_bool(name, default='false'):
    return os.getenv(name, default).lower() in {'true', '1', 'yes'}


@dataclass
class LDRMConfig:
    ENABLED: bool = field(default_factory=lambda: env_bool('LDRM_ENABLED'))
    # Demo mode is an explicit operator decision. It must never be the default:
    # it enables synthetic identities, synthetic cases and mock transports.
    DEMO_MODE: bool = field(default_factory=lambda: env_bool('LDRM_DEMO_MODE', 'false'))
    # Platform-wide demonstration marker (DFAP_DEMO_MODE). When either this or
    # DEMO_MODE is set the platform is in demonstration operation and no
    # production external dispatch may occur.
    DFAP_DEMO_MODE: bool = field(default_factory=lambda: env_bool('DFAP_DEMO_MODE', 'false'))
    # Global production kill switch. Default false. When false no PRODUCTION
    # external dispatch may occur under any combination of other conditions.
    PRODUCTION_DISPATCH_ENABLED: bool = field(default_factory=lambda: env_bool('LDRM_PRODUCTION_DISPATCH_ENABLED', 'false'))
    STORAGE_DIR: str = field(default_factory=lambda: os.getenv('LDRM_STORAGE_DIR', './data/ldrm'))
    MAX_ATTACHMENT_SIZE_BYTES: int = 100 * 1024 * 1024
    DEFAULT_REQUEST_TIMEOUT_DAYS: int = 30
    USE_MOCK_PROVIDERS_ONLY: bool = True
    # Warn this many days before a certificate or integration profile expires.
    EXPIRY_WARNING_DAYS: int = 30

    @property
    def demonstration_mode(self) -> bool:
        """True when the deployment is running as a demonstration."""
        return self.DEMO_MODE or self.DFAP_DEMO_MODE

    def production_dispatch_permitted(self) -> tuple[bool, str]:
        """Single source of truth for whether production dispatch may be attempted."""
        if not self.ENABLED:
            return False, 'LDRM is globally disabled (LDRM_ENABLED=false)'
        if self.demonstration_mode:
            return False, 'Demonstration mode is active; production external dispatch is prohibited'
        if not self.PRODUCTION_DISPATCH_ENABLED:
            return False, 'Production dispatch is globally DISABLED (LDRM_PRODUCTION_DISPATCH_ENABLED=false)'
        if self.USE_MOCK_PROVIDERS_ONLY:
            return False, 'This build only implements mock provider transport (USE_MOCK_PROVIDERS_ONLY=true)'
        return True, ''


ldrm_settings = LDRMConfig()

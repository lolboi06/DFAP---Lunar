"""
Lawful Data Request Module (LDRM) for DFAP.

A modular subsystem for requesting, authorizing, dispatching, and receiving
lawfully authorized CDR, IPDR, BANK, and SOCIAL datasets.
"""

from dfap.ldrm_subsystem.config import LDRMConfig, ldrm_settings

__all__ = ["LDRMConfig", "ldrm_settings"]

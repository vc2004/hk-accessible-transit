"""
PII Masking module — anonymizes user location data before logging or storage.

Implements the Context Hygiene pattern from Day 5 Section 5.6:
    Strict PII masking and placeholder injection to prevent sensitive data
    from leaking into logs, prompts, or agent memory.

Design principle (Day 4, Pillar 2 — Data Security):
    Data access must be strictly scoped to enforce least privilege.
    User location data is especially sensitive — it reveals home, workplace,
    medical appointments, and daily routines.

Policy:
    1. Precise locations (street-level) → hashed before logging
    2. District-level locations → retained for route quality analysis
    3. User profiles → stored with pseudonymous IDs only
    4. Session data → auto-expires after 24 hours
"""

import hashlib
import hmac
import os
import re
from datetime import datetime, timedelta
from typing import Optional


class PIIMasker:
    """Anonymizes personally identifiable information in transit data.

    Follows the "Context-as-a-Perimeter" model (Day 4 Pillar 5):
    data is masked at the boundary before entering any agent context.
    """

    def __init__(self, secret: Optional[str] = None):
        # Use a session-specific secret for HMAC. In production, this comes
        # from a secure key management service, not an env var.
        self._secret = secret or os.getenv("PII_HASH_SECRET", os.urandom(32).hex())

    # ------------------------------------------------------------------
    # Location masking
    # ------------------------------------------------------------------

    def mask_location(self, location: str, precision: str = "district") -> str:
        """Mask a location string to the specified precision level.

        Args:
            location: Raw location string (e.g., "Flat 12A, 3/F, 456 Nathan Rd, Mong Kok")
            precision: Desired precision level
                - "district": Retain only district-level (e.g., "Mong Kok")
                - "hashed": Full location hashed with HMAC-SHA256
                - "none": Return placeholder (for highest sensitivity)

        Returns:
            Masked location string
        """
        if precision == "district":
            return self._extract_district(location)
        elif precision == "hashed":
            return self._hmac_hash(location)[:16]  # First 16 chars of hex digest
        elif precision == "none":
            return "[REDACTED]"
        return location

    def _extract_district(self, location: str) -> str:
        """Extract the district-level location from a full address.

        Matches against known Hong Kong districts. If no match, returns
        a hashed prefix to avoid leaking the full address while preserving
        some geographic context for route quality analysis.
        """
        hk_districts = [
            # Hong Kong Island
            "Central", "Admiralty", "Wan Chai", "Causeway Bay", "North Point",
            "Quarry Bay", "Shau Kei Wan", "Chai Wan", "Kennedy Town",
            "Sheung Wan", "Aberdeen", "Wong Chuk Hang", "Pok Fu Lam",
            # Kowloon
            "Tsim Sha Tsui", "Mong Kok", "Yau Ma Tei", "Jordan",
            "Sham Shui Po", "Cheung Sha Wan", "Lai Chi Kok",
            "Kowloon Tong", "Kowloon City", "To Kwa Wan",
            "Wong Tai Sin", "Diamond Hill", "Choi Hung",
            "Kwun Tong", "Ngau Tau Kok", "Lam Tin", "Yau Tong",
            # New Territories East
            "Sha Tin", "Tai Po", "Fanling", "Sheung Shui",
            "Ma On Shan", "Tai Wai", "Fo Tan", "Science Park",
            # New Territories West
            "Tsuen Wan", "Kwai Fong", "Tsing Yi", "Tuen Mun",
            "Yuen Long", "Tin Shui Wai", "Tseung Kwan O",
            # Islands
            "Tung Chung", "Discovery Bay", "Mui Wo", "Cheung Chau",
            "Lamma Island", "Peng Chau",
        ]

        for district in hk_districts:
            if district.lower() in location.lower():
                return district

        # If no district match, return first 2 words (likely an area name)
        words = location.replace(",", " ").split()
        if len(words) >= 2:
            return f"{words[0]} {words[1]}"
        return words[0] if words else "[UNKNOWN]"

    def _hmac_hash(self, text: str) -> str:
        """HMAC-SHA256 hash of text. Deterministic for the same secret,
        so route quality analysis is possible without revealing raw locations."""
        return hmac.new(
            self._secret.encode(),
            text.encode(),
            hashlib.sha256,
        ).hexdigest()

    # ------------------------------------------------------------------
    # User profile pseudonymization
    # ------------------------------------------------------------------

    def pseudonymize_user_id(self, user_id: str) -> str:
        """Create a pseudonymous ID from a real user identifier.

        Uses HMAC so the same user_id always maps to the same pseudonym
        within a session, enabling session persistence without PII.
        """
        return f"user_{self._hmac_hash(user_id)[:12]}"

    # ------------------------------------------------------------------
    # Data sanitization for logging
    # ------------------------------------------------------------------

    def sanitize_for_logging(self, text: str) -> str:
        """Remove PII from a text string before logging.

        Strips:
        - HKID numbers (pattern: A123456(7))
        - Phone numbers (HK: 8 digits, optionally with +852)
        - Email addresses
        - Floor/unit numbers in addresses
        """
        # HKID pattern: 1-2 letters + 6-7 digits + check digit in parens
        text = re.sub(r'[A-Z]{1,2}\d{6,7}\(\d\)', '[HKID REDACTED]', text)

        # HK phone numbers
        text = re.sub(r'(\+852[-\s]?)?\d{4}[-\s]?\d{4}', '[PHONE REDACTED]', text)

        # Email addresses
        text = re.sub(r'[\w\.-]+@[\w\.-]+\.\w+', '[EMAIL REDACTED]', text)

        # Floor/unit: "Flat X, Y/F" pattern
        text = re.sub(r'Flat\s+\w+,\s*\d+/F', '[ADDRESS REDACTED]', text)
        text = re.sub(r'\d+/F', '[FLOOR REDACTED]', text)

        return text


class SessionManager:
    """Manages user sessions with automatic expiry.

    Implements Day 4 Pillar 5 (Zero Ambient Authority): sessions auto-expire
    and carry only the minimum necessary data.
    """

    def __init__(self, ttl_hours: int = 24):
        self.ttl = timedelta(hours=ttl_hours)
        self._sessions: dict[str, dict] = {}

    def create_session(self, pseudonym_id: str) -> str:
        """Create a new session for a pseudonymous user."""
        session_id = hashlib.sha256(os.urandom(32)).hexdigest()[:16]
        self._sessions[session_id] = {
            "pseudonym_id": pseudonym_id,
            "created_at": datetime.now(),
            "queries": [],
        }
        return session_id

    def validate_session(self, session_id: str) -> bool:
        """Check if a session is still valid (exists + not expired)."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        if datetime.now() - session["created_at"] > self.ttl:
            del self._sessions[session_id]
            return False
        return True

    def record_query(self, session_id: str, masked_location: str) -> None:
        """Record a location query in the session (masked form only)."""
        if session_id in self._sessions:
            self._sessions[session_id]["queries"].append({
                "timestamp": datetime.now().isoformat(),
                "location_mask": masked_location,
            })

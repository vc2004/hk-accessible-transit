"""
Input Sanitizer — prevents injection attacks and validates user inputs.

Implements Day 5 Section 5.6 (Context Hygiene):
    All user inputs are sanitized before entering the agent context.
    This prevents prompt injection, command injection, and data poisoning.

Also implements Day 4 Pillar 4 (Application & Runtime Security):
    Deploy LLM Firewall for dynamic prompt and response filtering.

Design: shift intelligence left — deterministic validation where possible,
LLM-based validation only for genuinely ambiguous cases.
"""

import re
from typing import Optional


class InputSanitizer:
    """Validates and sanitizes user inputs before agent processing.

    All methods are deterministic — no LLM calls in the sanitization path.
    This is a hard security boundary: if the sanitizer can't validate it,
    the input doesn't reach the agent.
    """

    # Maximum input length (prevents context window stuffing attacks)
    MAX_INPUT_LENGTH = 500

    # Characters allowed in location names (English, Chinese, common punctuation)
    LOCATION_PATTERN = re.compile(
        r'^[\w\s\-\(\)\.\,\'\-'
        r'一-鿿'   # CJK Unified Ideographs
        r'　-〿'   # CJK Symbols and Punctuation
        r'㄀-ㄯ'   # Bopomofo
        r']+$',
        re.UNICODE,
    )

    # Patterns that indicate injection attempts (always rejected)
    INJECTION_SIGNATURES = [
        # Prompt injection
        r'ignore\s+(all\s+)?(previous|above)\s+instructions',
        r'system\s*prompt\s*:',
        r'<\|im_start\|>',
        r'<\|im_end\|>',
        r'\[INST\]',
        r'\[/INST\]',
        r'<<SYS>>',
        r'<</SYS>>',

        # Command injection
        r'`[^`]+`',           # Backtick command substitution
        r'\$\([^)]+\)',        # Dollar-paren command substitution
        r'&&\s*\w+',           # Shell chaining
        r'\|\|\s*\w+',         # Shell OR
        r';\s*\w+',            # Shell command separator
        r'\]\s*\]',            # Closing brackets (used in some injections)

        # SQL injection (defense in depth — shouldn't reach here)
        r'\bUNION\s+SELECT\b',
        r'\bDROP\s+TABLE\b',
        r"'\s*OR\s+'1'\s*=\s*'1",

        # Script injection
        r'<\s*script',
        r'javascript\s*:',
        r'onerror\s*=',
        r'onload\s*=',
    ]

    # Known Hong Kong place names for validation
    _KNOWN_PLACES: set[str] = {
        # Hong Kong Island
        "central", "admiralty", "wan chai", "causeway bay", "north point",
        "quarry bay", "shau kei wan", "chai wan", "kennedy town",
        "sheung wan", "sai ying pun", "aberdeen", "wong chuk hang",
        "pok fu lam", "happy valley", "stanley", "repulse bay",
        # Kowloon
        "tsim sha tsui", "mong kok", "yau ma tei", "jordan",
        "sham shui po", "cheung sha wan", "lai chi kok",
        "kowloon tong", "kowloon city", "to kwa wan",
        "wong tai sin", "diamond hill", "choi hung",
        "kwun tong", "ngau tau kok", "lam tin", "yau tong",
        "lok fu", "shek kip mei", "ho man tin", "hung hom",
        # New Territories East
        "sha tin", "tai po", "tai po market", "fanling", "sheung shui",
        "ma on shan", "tai wai", "fo tan", "science park",
        "sai kung", "tseung kwan o", "hang hau", "po lam", "lohas park",
        # New Territories West
        "tsuen wan", "kwai fong", "kwai hing", "tsing yi",
        "tuen mun", "yuen long", "tin shui wai",
        # Islands
        "tung chung", "discovery bay", "mui wo", "cheung chau",
        "airport", "asiaworld-expo", "tsing ma",
    }

    def __init__(self):
        # Compile injection patterns for performance
        self._injection_regexes = [
            re.compile(pattern, re.IGNORECASE)
            for pattern in self.INJECTION_SIGNATURES
        ]

    # ------------------------------------------------------------------
    # Main API
    # ------------------------------------------------------------------

    def sanitize(self, raw_input: str) -> tuple[str, list[str]]:
        """Sanitize user input. Returns (cleaned_input, list_of_warnings).

        This is the main entry point. All user inputs pass through here
        before reaching any agent.
        """
        warnings: list[str] = []

        # Step 1: Length check (prevents context window stuffing)
        if len(raw_input) > self.MAX_INPUT_LENGTH:
            raw_input = raw_input[:self.MAX_INPUT_LENGTH]
            warnings.append(
                f"Input truncated to {self.MAX_INPUT_LENGTH} characters"
            )

        # Step 2: Injection check (hard block)
        for regex in self._injection_regexes:
            if regex.search(raw_input):
                # Don't return the raw match — could contain the injection
                pattern_name = regex.pattern[:50]
                raise InputRejectedError(
                    f"Input rejected: potential injection pattern detected "
                    f"({pattern_name}...)"
                )

        # Step 3: Strip control characters
        cleaned = self._strip_control_chars(raw_input)
        if cleaned != raw_input:
            warnings.append("Control characters removed from input")

        # Step 4: Normalize whitespace
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()

        return cleaned, warnings

    def validate_location(self, location: str) -> bool:
        """Check if a location string looks like a valid Hong Kong place name.

        Returns True if the location is recognized or matches expected patterns.
        Returns False if it contains suspicious content.
        """
        location_lower = location.lower().strip()

        # Check against known places
        for known in self._KNOWN_PLACES:
            if known in location_lower or location_lower in known:
                return True

        # Check character set (allow English + Chinese + common punctuation)
        if self.LOCATION_PATTERN.match(location):
            return True

        return False

    def suggest_location(self, partial: str) -> list[str]:
        """Suggest known locations matching a partial input.

        Helps users correct typos and prevents the agent from hallucinating
        non-existent station names (Day 4: slopsquatting prevention).
        """
        partial_lower = partial.lower().strip()
        matches = []
        for place in self._KNOWN_PLACES:
            if partial_lower in place:
                matches.append(place.title())
        return sorted(matches)[:5]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_control_chars(text: str) -> str:
        """Remove control characters except common whitespace."""
        return ''.join(
            char for char in text
            if char.isprintable() or char in ('\n', '\r', '\t')
        )


class InputRejectedError(ValueError):
    """Raised when an input is rejected by the sanitizer."""
    pass

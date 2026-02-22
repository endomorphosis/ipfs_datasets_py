"""
TDFOL Security Validator - Enterprise-Grade Security for Theorem Proving

This module provides comprehensive security validation for TDFOL (Typed Distributed
First-Order Logic) theorem proving, including input validation, ZKP security audits,
resource limits, DoS prevention, and formula sanitization.

Phase 12 Task 12.2 - Security Validation Implementation
"""

import re
import time
import hashlib
import logging
from typing import Dict, List, Optional, Set, Tuple, Any, Union
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import threading
from datetime import datetime, timedelta


logger = logging.getLogger(__name__)


class SecurityLevel(Enum):
    """Security enforcement levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PARANOID = "paranoid"


class ThreatType(Enum):
    """Types of security threats."""
    INJECTION = "injection"
    DOS = "dos"
    RESOURCE_EXHAUSTION = "resource_exhaustion"
    MALFORMED_INPUT = "malformed_input"
    SIDE_CHANNEL = "side_channel"
    TIMING_ATTACK = "timing_attack"
    RECURSIVE_BOMB = "recursive_bomb"
    INVALID_ZKP = "invalid_zkp"


@dataclass
class ValidationResult:
    """Result of security validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    threats: List[ThreatType] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AuditResult:
    """Result of ZKP security audit."""
    passed: bool
    vulnerabilities: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    risk_level: str = "low"
    audit_time: float = 0.0


@dataclass
class SecurityConfig:
    """Security configuration parameters."""
    # Formula limits
    max_formula_size: int = 10000
    max_formula_depth: int = 100
    max_variables: int = 1000
    max_operators: int = 5000
    
    # Resource limits
    max_memory_mb: int = 500
    max_proof_time_seconds: float = 30.0
    max_stack_depth: int = 1000
    
    # Rate limiting
    max_requests_per_minute: int = 100
    max_concurrent_requests: int = 10
    
    # Security level
    security_level: SecurityLevel = SecurityLevel.MEDIUM
    
    # Character validation
    allowed_chars: Set[str] = field(default_factory=lambda: set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        "()[]{}∀∃∧∨¬→↔=≠<>≤≥+-*/,.:_' "
    ))
    
    # Pattern blacklist
    dangerous_patterns: List[str] = field(default_factory=lambda: [
        r"__.*__",  # Python internals
        r"eval",
        r"exec",
        r"compile",
        r"import",
        r"__import__",
        r"getattr",
        r"setattr",
        r"delattr",
    ])


class RateLimiter:
    """Thread-safe rate limiter for DoS prevention."""
    
    def __init__(self, max_requests: int, time_window: float):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum number of requests allowed
            time_window: Time window in seconds
        """
        self.max_requests = max_requests
        self.time_window = time_window
        self.requests: Dict[str, List[float]] = defaultdict(list)
        self.lock = threading.Lock()
    
    def check_rate_limit(self, identifier: str) -> Tuple[bool, Optional[str]]:
        """
        Check if request is within rate limit.
        
        Args:
            identifier: Unique identifier for the requester
            
        Returns:
            Tuple of (allowed, error_message)
        """
        with self.lock:
            current_time = time.time()
            
            # Clean old requests
            self.requests[identifier] = [
                t for t in self.requests[identifier]
                if current_time - t < self.time_window
            ]
            
            # Check limit
            if len(self.requests[identifier]) >= self.max_requests:
                return False, f"Rate limit exceeded: {len(self.requests[identifier])}/{self.max_requests} requests in {self.time_window}s"
            
            # Add new request
            self.requests[identifier].append(current_time)
            return True, None


class SecurityValidator:
    """
    Enterprise-grade security validator for TDFOL theorem proving.
    
    Provides comprehensive security validation including:
    - Input validation and sanitization
    - ZKP security audits
    - Resource limit enforcement
    - DoS prevention
    - Threat detection and logging
    """
    
    def __init__(self, config: Optional[SecurityConfig] = None):
        """
        Initialize security validator.
        
        Args:
            config: Security configuration (uses defaults if None)
        """
        self.config = config or SecurityConfig()
        self.rate_limiter = RateLimiter(
            self.config.max_requests_per_minute,
            60.0
        )
        self.concurrent_requests = 0
        self.concurrent_lock = threading.Lock()
        self.security_events: List[Dict[str, Any]] = []
        self.threat_patterns = self._compile_threat_patterns()
    
    def _compile_threat_patterns(self) -> List[re.Pattern]:
        """Compile regex patterns for threat detection."""
        return [re.compile(pattern) for pattern in self.config.dangerous_patterns]
    
    def validate_formula(self, formula: str, identifier: str = "default") -> ValidationResult:
        """
        Validate formula for security threats.
        
        Args:
            formula: Formula string to validate
            identifier: Unique identifier for rate limiting
            
        Returns:
            ValidationResult with validation status and details
        """
        result = ValidationResult(valid=True)
        
        try:
            # Check rate limit
            allowed, error_msg = self.rate_limiter.check_rate_limit(identifier)
            if not allowed:
                result.valid = False
                result.errors.append(error_msg)
                result.threats.append(ThreatType.DOS)
                self._log_security_event(ThreatType.DOS, error_msg, identifier)
                return result
            
            # Atomically acquire a concurrent request slot (check-and-increment).
            # The old two-step _check_concurrent_limit() + separate increment had a
            # TOCTOU race between multiple threads; _acquire_concurrent_slot() fixes
            # this by performing both operations inside a single lock acquisition.
            if not self._acquire_concurrent_slot():
                result.valid = False
                result.errors.append("Too many concurrent requests")
                result.threats.append(ThreatType.DOS)
                return result
            
            try:
                # Yield the GIL while the slot is held so that other threads can
                # also try to acquire a slot concurrently.  time.sleep(0) is a
                # cooperative thread yield with essentially zero elapsed time.
                time.sleep(0)

                # Input validation
                self._validate_input(formula, result)
                
                # Size and complexity checks
                self._check_size_limits(formula, result)
                
                # Character validation
                self._validate_characters(formula, result)
                
                # Injection detection
                self._detect_injection(formula, result)
                
                # DoS pattern detection
                self._detect_dos_patterns(formula, result)
                
                # Recursive bomb detection
                self._detect_recursive_bombs(formula, result)
                
                # Store metadata
                result.metadata = {
                    "formula_length": len(formula),
                    "validation_time": time.time(),
                    "security_level": self.config.security_level.value,
                }
                
            finally:
                # Decrement concurrent counter
                with self.concurrent_lock:
                    self.concurrent_requests -= 1
            
        except Exception as e:
            result.valid = False
            result.errors.append(f"Validation error: {str(e)}")
            logger.error(f"Validation exception: {e}", exc_info=True)
        
        return result
    
    def _check_concurrent_limit(self) -> bool:
        """Check if concurrent request limit is exceeded (non-atomic, legacy)."""
        with self.concurrent_lock:
            return self.concurrent_requests < self.config.max_concurrent_requests

    def _acquire_concurrent_slot(self) -> bool:
        """Atomically check and increment concurrent request counter.

        Returns True and increments the counter if a slot is available;
        returns False (without incrementing) if the limit is already reached.
        Using a single lock acquisition avoids the TOCTOU race in the separate
        check-then-increment pattern.
        """
        with self.concurrent_lock:
            if self.concurrent_requests < self.config.max_concurrent_requests:
                self.concurrent_requests += 1
                return True
            return False
    
    def _validate_input(self, formula: str, result: ValidationResult) -> None:
        """Validate basic input properties."""
        if not formula:
            result.valid = False
            result.errors.append("Empty formula")
            result.threats.append(ThreatType.MALFORMED_INPUT)
            return
        
        if not isinstance(formula, str):
            result.valid = False
            result.errors.append("Formula must be a string")
            result.threats.append(ThreatType.MALFORMED_INPUT)
            return
        
        # Check for null bytes
        if '\x00' in formula:
            result.valid = False
            result.errors.append("Null bytes not allowed")
            result.threats.append(ThreatType.INJECTION)
    
    def _check_size_limits(self, formula: str, result: ValidationResult) -> None:
        """Check formula size and complexity limits."""
        # Size limit
        if len(formula) > self.config.max_formula_size:
            result.valid = False
            result.errors.append(
                f"Formula too large: {len(formula)} > {self.config.max_formula_size}"
            )
            result.threats.append(ThreatType.RESOURCE_EXHAUSTION)
        
        # Depth limit (nested parentheses)
        depth = self._calculate_depth(formula)
        if depth > self.config.max_formula_depth:
            result.valid = False
            result.errors.append(
                f"Formula too deep: {depth} > {self.config.max_formula_depth}"
            )
            result.threats.append(ThreatType.RESOURCE_EXHAUSTION)
        
        # Variable count
        var_count = len(re.findall(r'\b[a-z][a-z0-9_]*\b', formula))
        if var_count > self.config.max_variables:
            result.valid = False
            result.errors.append(
                f"Too many variables: {var_count} > {self.config.max_variables}"
            )
            result.threats.append(ThreatType.RESOURCE_EXHAUSTION)
        
        # Operator count
        op_count = len(re.findall(r'[∀∃∧∨¬→↔=≠<>≤≥]', formula))
        if op_count > self.config.max_operators:
            result.valid = False
            result.errors.append(
                f"Too many operators: {op_count} > {self.config.max_operators}"
            )
            result.threats.append(ThreatType.RESOURCE_EXHAUSTION)
    
    def _calculate_depth(self, formula: str) -> int:
        """Calculate maximum nesting depth of parentheses."""
        max_depth = 0
        current_depth = 0
        
        for char in formula:
            if char in '([{':
                current_depth += 1
                max_depth = max(max_depth, current_depth)
            elif char in ')]}':
                current_depth = max(0, current_depth - 1)
        
        return max_depth
    
    def _validate_characters(self, formula: str, result: ValidationResult) -> None:
        """Validate that formula contains only allowed characters."""
        if self.config.security_level in [SecurityLevel.HIGH, SecurityLevel.PARANOID]:
            invalid_chars = set(formula) - self.config.allowed_chars
            if invalid_chars:
                if self.config.security_level == SecurityLevel.PARANOID:
                    result.valid = False
                    result.errors.append(
                        f"Invalid characters: {', '.join(repr(c) for c in invalid_chars)}"
                    )
                    result.threats.append(ThreatType.INJECTION)
                else:
                    result.warnings.append(
                        f"Unusual characters: {', '.join(repr(c) for c in invalid_chars)}"
                    )
    
    def _detect_injection(self, formula: str, result: ValidationResult) -> None:
        """Detect potential injection attacks."""
        # Check for dangerous patterns
        for pattern in self.threat_patterns:
            if pattern.search(formula):
                result.valid = False
                result.errors.append(f"Dangerous pattern detected: {pattern.pattern}")
                result.threats.append(ThreatType.INJECTION)
                self._log_security_event(
                    ThreatType.INJECTION,
                    f"Pattern: {pattern.pattern}",
                    formula[:100]
                )
        
        # Check for command injection attempts
        dangerous_sequences = ['$(', '`', '${', '|', ';', '&&', '||']
        for seq in dangerous_sequences:
            if seq in formula:
                if self.config.security_level in [SecurityLevel.HIGH, SecurityLevel.PARANOID]:
                    result.valid = False
                    result.errors.append(f"Dangerous sequence detected: {seq}")
                    result.threats.append(ThreatType.INJECTION)
                else:
                    result.warnings.append(f"Potentially dangerous sequence: {seq}")
    
    def _detect_dos_patterns(self, formula: str, result: ValidationResult) -> None:
        """Detect DoS attack patterns."""
        # Excessive repetition
        if self._has_excessive_repetition(formula):
            result.valid = False
            result.errors.append("Excessive character repetition detected")
            result.threats.append(ThreatType.DOS)
        
        # Exponential blowup patterns
        if self._has_exponential_pattern(formula):
            result.warnings.append("Potentially expensive formula detected")
            if self.config.security_level == SecurityLevel.PARANOID:
                result.valid = False
                result.threats.append(ThreatType.DOS)
    
    def _has_excessive_repetition(self, formula: str, threshold: int = 100) -> bool:
        """Check for excessive character repetition."""
        for i in range(len(formula) - threshold):
            if len(set(formula[i:i+threshold])) < 5:
                return True
        return False
    
    def _has_exponential_pattern(self, formula: str) -> bool:
        """Check for patterns that could cause exponential complexity."""
        # Look for deeply nested quantifiers
        quantifier_depth = 0
        max_quantifier_depth = 0
        
        i = 0
        while i < len(formula):
            if formula[i] in '∀∃':
                quantifier_depth += 1
                max_quantifier_depth = max(max_quantifier_depth, quantifier_depth)
            elif formula[i] in '.':  # End of quantifier scope
                quantifier_depth = max(0, quantifier_depth - 1)
            i += 1
        
        return max_quantifier_depth > 10
    
    def _detect_recursive_bombs(self, formula: str, result: ValidationResult) -> None:
        """Detect recursive bomb patterns."""
        # Check for self-referential patterns
        if re.search(r'(\w+)\s*=.*\1', formula):
            result.warnings.append("Self-referential pattern detected")
            if self.config.security_level in [SecurityLevel.HIGH, SecurityLevel.PARANOID]:
                result.threats.append(ThreatType.RECURSIVE_BOMB)
        
        # Check for circular references
        variables = re.findall(r'\b[a-z][a-z0-9_]*\b', formula)
        if len(variables) != len(set(variables)):
            duplicates = len(variables) - len(set(variables))
            if duplicates > 10:
                result.warnings.append(f"High variable reuse: {duplicates} duplicates")
    
    def sanitize_input(self, input_str: str) -> str:
        """
        Sanitize input string for safe processing.
        
        Args:
            input_str: Input string to sanitize
            
        Returns:
            Sanitized string
        """
        if not input_str:
            return ""
        
        # Remove null bytes
        sanitized = input_str.replace('\x00', '')
        
        # Remove dangerous patterns
        for pattern in self.threat_patterns:
            sanitized = pattern.sub('', sanitized)
        
        # Normalize whitespace
        sanitized = re.sub(r'\s+', ' ', sanitized)
        
        # Remove control characters (except newlines and tabs)
        sanitized = ''.join(
            c for c in sanitized
            if c.isprintable() or c in '\n\t'
        )
        
        # Limit length
        if len(sanitized) > self.config.max_formula_size:
            sanitized = sanitized[:self.config.max_formula_size]
        
        return sanitized.strip()
    
    def check_resource_limits(
        self,
        formula: str,
        memory_mb: Optional[float] = None,
        time_seconds: Optional[float] = None
    ) -> bool:
        """
        Check if formula is within resource limits.
        
        Args:
            formula: Formula to check
            memory_mb: Current memory usage in MB
            time_seconds: Current execution time in seconds
            
        Returns:
            True if within limits, False otherwise
        """
        # Check memory limit
        if memory_mb is not None and memory_mb > self.config.max_memory_mb:
            logger.warning(f"Memory limit exceeded: {memory_mb} > {self.config.max_memory_mb}")
            return False
        
        # Check time limit
        if time_seconds is not None and time_seconds > self.config.max_proof_time_seconds:
            logger.warning(f"Time limit exceeded: {time_seconds} > {self.config.max_proof_time_seconds}")
            return False
        
        # Check formula complexity
        result = ValidationResult(valid=True)
        self._check_size_limits(formula, result)
        
        return result.valid
    
    def audit_zkp_proof(
        self,
        proof: Dict[str, Any],
        formula: Optional[str] = None
    ) -> AuditResult:
        """
        Audit ZKP proof for security vulnerabilities.
        
        Args:
            proof: ZKP proof to audit
            formula: Optional formula associated with proof
            
        Returns:
            AuditResult with audit findings
        """
        start_time = time.time()
        result = AuditResult(passed=True)
        
        try:
            # Validate proof structure
            self._validate_proof_structure(proof, result)
            
            # Check cryptographic parameters
            self._check_crypto_parameters(proof, result)
            
            # Test for timing attacks
            self._test_timing_attacks(proof, result)
            
            # Check proof integrity
            self._check_proof_integrity(proof, result)
            
            # Side-channel analysis
            self._analyze_side_channels(proof, result)
            
            # Determine risk level
            result.risk_level = self._calculate_risk_level(result)
            
        except Exception as e:
            result.passed = False
            result.vulnerabilities.append(f"Audit error: {str(e)}")
            result.risk_level = "high"
            logger.error(f"ZKP audit exception: {e}", exc_info=True)
        
        result.audit_time = time.time() - start_time
        return result
    
    def _validate_proof_structure(self, proof: Dict[str, Any], result: AuditResult) -> None:
        """Validate ZKP proof structure."""
        required_fields = ['commitment', 'challenge', 'response']
        
        for field in required_fields:
            if field not in proof:
                result.passed = False
                result.vulnerabilities.append(f"Missing required field: {field}")
        
        # Check for unexpected fields
        expected_fields = set(required_fields + ['metadata', 'timestamp', 'version'])
        unexpected = set(proof.keys()) - expected_fields
        if unexpected:
            result.recommendations.append(
                f"Unexpected fields in proof: {', '.join(unexpected)}"
            )
    
    def _check_crypto_parameters(self, proof: Dict[str, Any], result: AuditResult) -> None:
        """Check cryptographic parameters."""
        # Check commitment size
        if 'commitment' in proof:
            commitment = proof['commitment']
            if isinstance(commitment, (bytes, str)):
                if len(str(commitment)) < 32:
                    result.vulnerabilities.append("Commitment too short (< 32 bytes)")
                    result.passed = False
        
        # Check challenge randomness
        if 'challenge' in proof:
            challenge = proof['challenge']
            if isinstance(challenge, str):
                # Simple entropy check
                if len(set(challenge)) < len(challenge) // 4:
                    result.recommendations.append(
                        "Challenge appears to have low entropy"
                    )
    
    def _test_timing_attacks(self, proof: Dict[str, Any], result: AuditResult) -> None:
        """Test for timing attack vulnerabilities."""
        # Simulate multiple verifications and check timing consistency
        times = []
        test_iterations = 5 if self.config.security_level == SecurityLevel.PARANOID else 3
        
        for _ in range(test_iterations):
            start = time.perf_counter()
            # Simulate verification (hash computation)
            _ = hashlib.sha256(str(proof).encode()).hexdigest()
            times.append(time.perf_counter() - start)
        
        # Check timing variance
        if len(times) > 1:
            avg_time = sum(times) / len(times)
            variance = sum((t - avg_time) ** 2 for t in times) / len(times)
            
            if variance > avg_time * 0.5:  # High variance
                result.recommendations.append(
                    "High timing variance detected - potential timing attack vector"
                )
    
    def _check_proof_integrity(self, proof: Dict[str, Any], result: AuditResult) -> None:
        """Check proof integrity.

        The stored hash must equal the SHA-256 of the *non-metadata* proof fields
        (i.e. ``commitment``, ``challenge``, ``response``, …) serialised as a sorted
        list of items.  Excluding ``metadata`` itself from the hash avoids a
        self-referential dependency and matches what external signers produce.
        """
        # Verify proof hash if present
        if 'metadata' in proof and 'hash' in proof['metadata']:
            stored_hash = proof['metadata']['hash']
            # Hash only the core proof fields, excluding the 'metadata' wrapper
            proof_data = {k: v for k, v in proof.items() if k != 'metadata'}
            calculated_hash = hashlib.sha256(
                str(sorted(proof_data.items())).encode()
            ).hexdigest()

            if stored_hash != calculated_hash:
                result.passed = False
                result.vulnerabilities.append("Proof integrity check failed")
    
    def _analyze_side_channels(self, proof: Dict[str, Any], result: AuditResult) -> None:
        """Analyze potential side-channel vulnerabilities."""
        # Check for information leakage in metadata
        if 'metadata' in proof:
            metadata = proof['metadata']
            
            # Check for excessive metadata
            if len(str(metadata)) > 1000:
                result.recommendations.append(
                    "Large metadata could leak information"
                )
            
            # Check for sensitive field names
            sensitive_keywords = ['secret', 'private', 'key', 'password']
            for key in metadata:
                if any(keyword in str(key).lower() for keyword in sensitive_keywords):
                    result.vulnerabilities.append(
                        f"Potentially sensitive metadata field: {key}"
                    )
                    result.passed = False
    
    def _calculate_risk_level(self, result: AuditResult) -> str:
        """Calculate overall risk level."""
        if not result.passed:
            return "critical"
        
        vuln_count = len(result.vulnerabilities)
        rec_count = len(result.recommendations)
        
        if vuln_count > 0:
            return "high"
        elif rec_count > 3:
            return "medium"
        else:
            return "low"
    
    def detect_dos_pattern(self, formula: str) -> bool:
        """
        Detect DoS attack patterns in formula.
        
        Args:
            formula: Formula to analyze
            
        Returns:
            True if DoS pattern detected, False otherwise
        """
        result = ValidationResult(valid=True)
        self._detect_dos_patterns(formula, result)
        self._detect_recursive_bombs(formula, result)
        
        return ThreatType.DOS in result.threats or ThreatType.RECURSIVE_BOMB in result.threats
    
    def _log_security_event(
        self,
        threat_type: ThreatType,
        details: str,
        context: str
    ) -> None:
        """Log security event for monitoring."""
        event = {
            "timestamp": datetime.now().isoformat(),
            "threat_type": threat_type.value,
            "details": details,
            "context": context,
            "security_level": self.config.security_level.value,
        }
        self.security_events.append(event)
        logger.warning(f"Security event: {threat_type.value} - {details}")
    
    def get_security_report(self) -> Dict[str, Any]:
        """
        Generate security report.
        
        Returns:
            Dictionary containing security statistics and events
        """
        threat_counts = defaultdict(int)
        for event in self.security_events:
            threat_counts[event['threat_type']] += 1
        
        return {
            "total_events": len(self.security_events),
            "threat_breakdown": dict(threat_counts),
            "security_level": self.config.security_level.value,
            "config": {
                "max_formula_size": self.config.max_formula_size,
                "max_formula_depth": self.config.max_formula_depth,
                "max_requests_per_minute": self.config.max_requests_per_minute,
            },
            "recent_events": self.security_events[-10:],  # Last 10 events
        }
    
    def clear_security_events(self) -> None:
        """Clear security event log."""
        self.security_events.clear()


def create_validator(security_level: SecurityLevel = SecurityLevel.MEDIUM) -> SecurityValidator:
    """
    Create a security validator with specified security level.
    
    Args:
        security_level: Security enforcement level
        
    Returns:
        Configured SecurityValidator instance
    """
    config = SecurityConfig(security_level=security_level)
    return SecurityValidator(config)


# Convenience functions
def validate_formula(formula: str, security_level: SecurityLevel = SecurityLevel.MEDIUM) -> ValidationResult:
    """
    Validate formula with specified security level.
    
    Args:
        formula: Formula to validate
        security_level: Security enforcement level
        
    Returns:
        ValidationResult
    """
    validator = create_validator(security_level)
    return validator.validate_formula(formula)


def audit_proof(proof: Dict[str, Any]) -> AuditResult:
    """
    Audit ZKP proof for security vulnerabilities.
    
    Args:
        proof: ZKP proof to audit
        
    Returns:
        AuditResult
    """
    validator = create_validator()
    return validator.audit_zkp_proof(proof)

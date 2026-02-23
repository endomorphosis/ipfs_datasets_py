"""Security components for complaint generator optimizers."""

# Import modules to make them available without causing circular imports
# Use lazy imports or direct module imports instead of importing specific classes

__all__ = [
    # Input validation
    "InputValidator",
    "EntityValidator",
    "RelationshipValidator",
    "ValidationError",
    "ValidationLevel",
    "ValidationResult",
    # Rate limiting
    "TokenBucket",
    "TokenBucketRateLimiter",
    "PerEndpointRateLimiter",
    "RateLimitConfig",
    "RateLimitTier",
    "RateLimitExceeded",
    "RateLimitMiddleware",
]

def __getattr__(name):
    """Lazy import to avoid circular import issues."""
    if name in ["InputValidator", "EntityValidator", "RelationshipValidator", 
                "ValidationError", "ValidationLevel", "ValidationResult"]:
        from ipfs_datasets_py.optimizers.security import input_validation
        return getattr(input_validation, name)
    elif name in ["TokenBucket", "TokenBucketRateLimiter", "PerEndpointRateLimiter",
                  "RateLimitConfig", "RateLimitTier", "RateLimitExceeded", "RateLimitMiddleware"]:
        from ipfs_datasets_py.optimizers.security import rate_limiter
        return getattr(rate_limiter, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

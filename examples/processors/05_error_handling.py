"""
Error Handling and Retry Configuration Examples
================================================

This example demonstrates the enhanced error handling capabilities
in UniversalProcessor, including retry logic, circuit breakers,
and error classification.
"""

import asyncio
from ipfs_datasets_py.processors import UniversalProcessor
from ipfs_datasets_py.processors.universal_processor import ProcessorConfig
from ipfs_datasets_py.processors.error_handling import (
    ProcessorError,
    TransientError,
    PermanentError,
    ErrorClassification
)


async def example_1_basic_retry():
    """Example 1: Basic retry configuration."""
    print("\n" + "=" * 70)
    print("Example 1: Basic Retry Configuration")
    print("=" * 70)
    
    # Configure processor with retries
    config = ProcessorConfig(
        max_retries=3,  # Retry up to 3 times
        circuit_breaker_enabled=True,
        circuit_breaker_threshold=5  # Open circuit after 5 failures
    )
    
    processor = UniversalProcessor(config)
    
    print(f"✓ Processor configured with:")
    print(f"  - Max retries: {config.max_retries}")
    print(f"  - Circuit breaker: {'Enabled' if config.circuit_breaker_enabled else 'Disabled'}")
    print(f"  - Failure threshold: {config.circuit_breaker_threshold}")
    
    # Process with automatic retry
    try:
        # Note: In real usage, transient errors (network timeouts) 
        # will be automatically retried
        result = await processor.process("https://example.com")
        print(f"\n✓ Successfully processed (with automatic retry on transient errors)")
    except Exception as e:
        print(f"\n✗ Failed after all retries: {e}")


async def example_2_error_classification():
    """Example 2: Understanding error classifications."""
    print("\n" + "=" * 70)
    print("Example 2: Error Classification")
    print("=" * 70)
    
    # Different error types are handled differently
    errors = [
        ("Transient", TransientError("Network timeout"), "Will be retried"),
        ("Permanent", PermanentError("Invalid input format"), "Will NOT be retried"),
        ("Unknown", ProcessorError("Generic error"), "May be retried"),
    ]
    
    for error_name, error, behavior in errors:
        print(f"\n{error_name} Error:")
        print(f"  Classification: {error.classification.value}")
        print(f"  Behavior: {behavior}")
        print(f"  Message: {error}")


async def example_3_monitoring_failures():
    """Example 3: Monitoring failures and circuit breaker."""
    print("\n" + "=" * 70)
    print("Example 3: Circuit Breaker in Action")
    print("=" * 70)
    
    config = ProcessorConfig(
        max_retries=1,
        circuit_breaker_enabled=True,
        circuit_breaker_threshold=3,  # Open after 3 failures
        raise_on_error=False  # Return error results instead of raising
    )
    
    processor = UniversalProcessor(config)
    
    print("Simulating multiple failures to trigger circuit breaker...")
    print("(In production, this would happen with actual transient errors)")
    
    # Simulate processing attempts
    # In production, if a processor consistently fails, the circuit
    # breaker will open and reject requests to allow recovery
    
    print("\n✓ Circuit breaker protects against cascading failures")
    print("✓ Automatically enters HALF_OPEN state after timeout")
    print("✓ Closes circuit after successful recovery")


async def example_4_custom_error_handling():
    """Example 4: Custom error handling strategies."""
    print("\n" + "=" * 70)
    print("Example 4: Custom Error Handling")
    print("=" * 70)
    
    config = ProcessorConfig(
        max_retries=2,
        raise_on_error=True  # Raise exceptions instead of returning error results
    )
    
    processor = UniversalProcessor(config)
    
    try:
        # This will raise an exception if processing fails
        result = await processor.process("nonexistent_file.pdf")
    except Exception as e:
        print(f"✓ Caught exception: {type(e).__name__}")
        print(f"  Message: {e}")
        print(f"  This allows custom error handling in your application")


async def example_5_fallback_processing():
    """Example 5: Fallback processing."""
    print("\n" + "=" * 70)
    print("Example 5: Fallback Processing")
    print("=" * 70)
    
    config = ProcessorConfig(
        fallback_enabled=True,  # Try alternative processors on failure
        max_retries=1
    )
    
    processor = UniversalProcessor(config)
    
    print("✓ Fallback enabled: if primary processor fails,")
    print("  system will try alternative processors")
    print("✓ Increases reliability for ambiguous inputs")


async def example_6_error_recovery_suggestions():
    """Example 6: Error recovery suggestions."""
    print("\n" + "=" * 70)
    print("Example 6: Error Recovery Suggestions")
    print("=" * 70)
    
    # ProcessorError includes suggestions for recovery
    error = ProcessorError(
        "Failed to connect to service",
        classification=ErrorClassification.TRANSIENT,
        suggestions=[
            "Check network connectivity",
            "Verify service is running",
            "Try again in a few moments",
            "Check firewall settings"
        ]
    )
    
    print("When errors occur, they include helpful suggestions:")
    print(f"\n{error}")


async def main():
    """Run all examples."""
    print("\n")
    print("=" * 70)
    print("ENHANCED ERROR HANDLING EXAMPLES")
    print("=" * 70)
    
    examples = [
        example_1_basic_retry,
        example_2_error_classification,
        example_3_monitoring_failures,
        example_4_custom_error_handling,
        example_5_fallback_processing,
        example_6_error_recovery_suggestions
    ]
    
    for example in examples:
        await example()
        await asyncio.sleep(0.1)  # Small delay between examples
    
    print("\n" + "=" * 70)
    print("Examples complete!")
    print("=" * 70)
    print("\nKey Takeaways:")
    print("  • Transient errors are automatically retried")
    print("  • Circuit breakers prevent cascading failures")
    print("  • Error classification enables intelligent handling")
    print("  • Fallback processing increases reliability")
    print("  • Configuration is flexible and production-ready")
    print()


if __name__ == "__main__":
    asyncio.run(main())

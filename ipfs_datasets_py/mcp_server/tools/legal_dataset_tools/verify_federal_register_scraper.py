"""Federal Register verifier — thin MCP wrapper.

All domain logic lives at:
  ipfs_datasets_py.processors.legal_scrapers.federal_register_verifier
"""
import anyio
import sys

from ipfs_datasets_py.processors.legal_scrapers.federal_register_verifier import (  # noqa: F401
    FederalRegisterVerifier,
)

__all__ = ["FederalRegisterVerifier"]


async def main():
    """Main entry point for standalone verification."""
    verifier = FederalRegisterVerifier()
    exit_code = await verifier.run_all_tests()
    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        anyio.run(main)
    except KeyboardInterrupt:
        print("\n\nVerification cancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Verification failed with error: {e}")
        sys.exit(1)

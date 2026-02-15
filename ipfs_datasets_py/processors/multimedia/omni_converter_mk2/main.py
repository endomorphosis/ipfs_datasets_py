#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
from interfaces import make_cli

def main():
    cli = make_cli()
    return cli.main()  # Run the CLI interface

if __name__ == "__main__":
    try:
        outcode = main()
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        sys.exit(0)
    except Exception as e: # Unexpected error handling
        import traceback
        print(f"Unexpected {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
    else: # Should be called if no exceptions were raised
        sys.exit(outcode)
    finally: # Cleanup and teardown
        import teardown
        teardown.teardown()

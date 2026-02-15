#!/usr/bin/env python
# -*- coding: utf-8 -*-
import sys
from interfaces import make_cli

def main():
    outcode = 1  # Initialize exit code
    try:
        cli = make_cli()
        return cli.main()  # Run the CLI interface
    except KeyboardInterrupt:
        print("\nProcess interrupted by user.")
        outcode = 0
    except Exception as e: # Unexpected error handling
        import traceback
        print(f"Unexpected {type(e).__name__}: {e}")
        traceback.print_exc()
        outcode = 1
    finally: # Cleanup and teardown
        import teardown
        teardown.teardown()
        return outcode

if __name__ == "__main__":
    sys.exit(main())

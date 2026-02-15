def show_version() -> None:
    """Show version information."""
    from __version__ import __version__
    from datetime import datetime
    print(f"Omni-Converter version {__version__}")
    print("By Kyle Rose, Claude 3.7 Sonnet")
    print(f"MIT {datetime.now().year}")
    print("\nImplementation Status:")
    print("- Text formats: Fully implemented (HTML, XML, Plain text, CSV, Calendar)")
    print("- Image formats: Fully implemented (JPEG, PNG, GIF, WebP, SVG)")
    print("- Application formats: Fully implemented (PDF, JSON, DOCX, XLSX, ZIP)")
    print("- Audio formats: Fully implemented (MP3, WAV, OGG, FLAC, AAC)")
    print("- Video formats: Fully implemented (MP4, WebM, AVI, MKV, MOV)")
    print("\nSee ROADMAP.md for detailed status report.")

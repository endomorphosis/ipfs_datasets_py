
from core.text_normalizer import make_text_normalizer

def list_normalizers() -> None:
    """List all available text normalizers."""
    text_normalizer = make_text_normalizer()

    print("Omni-Converter Text Normalizers\n===============================\n\n")
    for normalizer in sorted(text_normalizer.applied_normalizers):
        print(f"- {normalizer}")

    print("\nUse --normalizers option to specify which normalizers to apply.")
    print("Example: --normalizers whitespace,line_endings")
    print("NOTE: Not all normalizers are available or applicable for all formats.")
    print("Check the documentation for more details on each normalizer and which formats they are applied to.")

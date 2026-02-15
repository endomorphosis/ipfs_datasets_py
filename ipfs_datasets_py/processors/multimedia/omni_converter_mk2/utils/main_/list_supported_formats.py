
from supported_formats import SupportedFormats

def list_supported_formats() -> None:
    """List all supported formats."""

    # Format the handler capabilities
    print("Omni-Converter Supported Formats\n===============================\n\n")

    # Get formats grouped by category from the registry
    categories = SupportedFormats.SUPPORTED_FORMATS

    # Print formats by category
    for category, formats in sorted(categories.items()):
        print(f"{category.capitalize()} Formats ({len(formats)}):")
        for fmt in sorted(formats):
            print(f"  - {fmt}")
        print()

def list_output_formats() -> None:
    """List all available output formats."""
    from core._processing_pipeline import processing_pipeline
    print("Omni-Converter Output Formats\n============================\n\n")

    formats = processing_pipeline.formatter.available_formats

    for fmt in sorted(formats):
        print(f"- {fmt}")

    print("\nUse -f or --format option to specify the output format.")
    print("Example: -f json")

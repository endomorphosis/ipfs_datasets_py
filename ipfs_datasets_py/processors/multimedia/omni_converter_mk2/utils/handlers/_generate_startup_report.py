from typing import Any

def generate_startup_report(processors: dict[str, tuple[str, Any, set]]) -> str:
    """
    Generate a startup summary report.
    
    Args:
        processors: Dictionary of processor instances
        
    Returns:
        Formatted startup report string
    """
    from logger import logger
    lines = ["", "=" * 60, "CONTENT PROCESSOR STARTUP REPORT", "=" * 60, ""]
    
    # Sort by alphabetical order
    processors = dict(sorted(processors.items()))
    total_processors = len(processors)
    fully_functional_count = 0
    fully_functional = []
    degraded = []
    missing_deps = set()

    for processor_name, processor in processors.items():
        if hasattr(processor[1], "processor_info"):
            info = processor[1].processor_info
            capabilities = info.get("capabilities", {})

            # Check if all capabilities are available
            all_available = all(cap["available"] for cap in capabilities.values())
            if all_available and capabilities:
                fully_functional_count += 1
                fully_functional.append(processor_name)
            elif any(not cap["available"] for cap in capabilities.values()):
                degraded.append(processor_name)

            # Track missing dependencies
            if info.get("implementation_used") == "mock":
                missing_deps.add(processor_name)

    lines.append(f"Total processors loaded: {total_processors}")
    lines.append(f"Fully functional: {fully_functional_count}")
    lines.append(f"DEGRADED: {len(degraded)}")

    if fully_functional_count == total_processors:
        lines.append("\nAll processors are fully functional.")
        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    if fully_functional:
        lines.append("\nProcessors with FULL capabilities:")
        for proc in fully_functional:
            lines.append(f"  {proc}")

    if degraded:
        lines.append("\nProcessors with DEGRADED capabilities:")
        for proc in degraded:
            lines.append(f"  WARNING: {proc}")

    if missing_deps:
        lines.append("\nTo restore full functionality, install missing dependencies:")
        lines.append("  pip install pillow opencv-python pydub beautifulsoup4 lxml")
        lines.append("  pip install pandas pypdf2 python-docx openpyxl")

    lines.append("\n" + "=" * 60)

    return "\n".join(lines)

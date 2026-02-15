from typing import Any

def generate_capability_report(processors: dict[str, Any]) -> str:
    """
    Generate a human-readable capability report.
    
    Args:
        processors: Dictionary of processor instances
        
    Returns:
        Formatted capability report string
    """
    lines = ["=" * 60, "PROCESSOR CAPABILITY REPORT", "=" * 60, ""]
    
    for processor_name, processor in sorted(processors.items()):
        lines.append(f"{processor_name}:")
        lines.append("-" * 40)
        
        if hasattr(processor[1], "processor_info"):
            info = processor[1].processor_info
            capabilities = info.get("capabilities", {})
            
            for cap_name, cap_info in sorted(capabilities.items()):
                if cap_info["available"]:
                    status = "✓"
                    impl = cap_info["implementation"]
                else:
                    status = "✗"
                    impl = "mock"
                lines.append(f"  {status} {cap_name} ({impl})")
                
            formats = info.get("supported_formats", set())
            if formats:
                lines.append(f"  Supported formats: {', '.join(sorted(formats))}")
        else:
            lines.append("  No processor info available")
            
        lines.append("")
    
    return "\n".join(lines)

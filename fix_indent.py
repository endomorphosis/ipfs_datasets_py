#\!/usr/bin/env python3

def reset_indentation():
    """Reset indentation in the file to original state (to start fresh)."""
    file_path = "./ipfs_datasets_py/rag_query_optimizer.py"
    
    with open(file_path, 'r') as file:
        content = file.read()
    
    # Make a backup
    with open(file_path + '.bak', 'w') as file:
        file.write(content)
        
    print("Backup saved to", file_path + '.bak')
    
    # Try to use black formatter if available
    try:
        import black
        print("Formatting with black...")
        mode = black.Mode()
        formatted_content = black.format_file_contents(content, fast=False, mode=mode)
        with open(file_path, 'w') as file:
            file.write(formatted_content)
        print("Formatting complete\!")
        return
    except (ImportError, ModuleNotFoundError):
        print("Black formatter not available, continuing with manual fix...")
    
    print("Fixing indentation manually...")
    
    # Just modify the class definition to fix methods
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if "class UnifiedGraphRAGQueryOptimizer" in line:
            print(f"Found class definition at line {i+1}")
            # Now process until end of file or next class
            j = i + 1
            while j < len(lines):
                # Stop at next class definition
                if "class " in lines[j] and not lines[j].startswith(" "):
                    break
                j += 1
            
            print(f"Class ends around line {j}")
            # Extract the class content
            class_lines = lines[i+1:j]
            
            # Fix the indentation
            fixed_class_lines = []
            
            for cl in class_lines:
                if cl.strip() == "":
                    fixed_class_lines.append(cl)
                    continue
                    
                # Remove all leading whitespace
                stripped = cl.lstrip()
                
                # Add the correct indentation
                if stripped.startswith("def "):
                    # Method definition gets 4 spaces
                    fixed_class_lines.append("    " + stripped)
                elif stripped.startswith('"""') and len(fixed_class_lines) > 0 and fixed_class_lines[-1].strip().endswith(":"):
                    # Docstring gets 8 spaces
                    fixed_class_lines.append("        " + stripped)
                elif stripped.endswith('"""') and not stripped.startswith('"""'):
                    # End of docstring gets 8 spaces
                    fixed_class_lines.append("        " + stripped)
                elif len(fixed_class_lines) > 0 and '"""' in fixed_class_lines[-1]:
                    # Lines inside docstring get 8 spaces
                    fixed_class_lines.append("        " + stripped)
                elif len(fixed_class_lines) > 0 and fixed_class_lines[-1].strip().endswith('"""'):
                    # First line after docstring gets 8 spaces
                    fixed_class_lines.append("        " + stripped)
                else:
                    # Method body gets 8 spaces
                    fixed_class_lines.append("        " + stripped)
            
            # Replace the class content
            lines[i+1:j] = fixed_class_lines
            break
    
    # Write the modified content back to the file
    with open(file_path, 'w') as file:
        file.write('\n'.join(lines))
    
    print("Manual indentation fix complete\!")

if __name__ == "__main__":
    reset_indentation()

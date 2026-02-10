# Test Markdown Document

## Introduction

This is a **test markdown file** for the omni converter project. Markdown is a lightweight markup language with plain-text formatting syntax.

## Features

### Text Formatting

- **Bold text** using double asterisks
- *Italic text* using single asterisks
- ***Bold and italic*** using triple asterisks
- ~~Strikethrough~~ using double tildes
- `Inline code` using backticks

### Lists

#### Unordered List
- First item
- Second item
  - Nested item 1
  - Nested item 2
- Third item

#### Ordered List
1. First step
2. Second step
3. Third step
   1. Sub-step A
   2. Sub-step B

### Code Blocks

```python
def fibonacci(n):
    """Generate Fibonacci sequence up to n terms."""
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    elif n == 2:
        return [0, 1]
    
    fib_sequence = [0, 1]
    for i in range(2, n):
        fib_sequence.append(fib_sequence[-1] + fib_sequence[-2])
    
    return fib_sequence

# Example usage
print(fibonacci(10))
```

### Links and Images

[Visit GitHub](https://github.com)

![Alt text for image](https://via.placeholder.com/150)

### Tables

| Header 1 | Header 2 | Header 3 |
|----------|----------|----------|
| Cell 1   | Cell 2   | Cell 3   |
| Cell 4   | Cell 5   | Cell 6   |
| Cell 7   | Cell 8   | Cell 9   |

### Blockquotes

> This is a blockquote. It can span multiple lines.
> 
> It can even have multiple paragraphs.

### Horizontal Rule

---

### Task Lists

- [x] Create test file
- [x] Add various markdown elements
- [ ] Test with converter
- [ ] Verify output

### Mathematical Expressions

When $a \ne 0$, there are two solutions to $ax^2 + bx + c = 0$:

$$x = \frac{-b \pm \sqrt{b^2 - 4ac}}{2a}$$

### Footnotes

Here's a sentence with a footnote[^1].

[^1]: This is the footnote content.

## Conclusion

This document demonstrates various Markdown features that should be properly handled by the omni converter.

---

*Last updated: 2025-05-24*
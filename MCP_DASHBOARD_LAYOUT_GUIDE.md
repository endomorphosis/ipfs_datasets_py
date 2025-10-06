# MCP Dashboard Layout Guide & CSS Framework

## Overview
This document provides comprehensive layout specifications for the MCP server dashboard, including XY coordinate positioning, responsive breakpoints, and CSS implementation guidelines.

## Layout Architecture

### Screen Resolution Targets
- **Primary**: 1920x1080 (Desktop)
- **Secondary**: 1366x768 (Laptop)
- **Minimum**: 1200x800 (Server console)

### Grid System Specifications

#### Header Bar
- **Position**: Fixed top
- **Height**: 70px
- **Width**: 100% viewport
- **Z-index**: 1000
- **Coordinates**: (0, 0) to (100vw, 70px)

```css
.dashboard-header {
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 70px;
    z-index: 1000;
    background: linear-gradient(135deg, #1e40af 0%, #2563eb 100%);
    border-bottom: 1px solid #e5e7eb;
}
```

#### Sidebar Navigation
- **Position**: Fixed left
- **Width**: 280px
- **Height**: calc(100vh - 70px)
- **Top offset**: 70px (below header)
- **Coordinates**: (0, 70px) to (280px, 100vh)

```css
.dashboard-sidebar {
    position: fixed;
    top: 70px;
    left: 0;
    width: 280px;
    height: calc(100vh - 70px);
    background: #f8fafc;
    border-right: 1px solid #e5e7eb;
    overflow-y: auto;
}
```

#### Main Content Area
- **Position**: Relative
- **Left margin**: 280px (sidebar width)
- **Top margin**: 70px (header height)
- **Width**: calc(100vw - 280px)
- **Coordinates**: (280px, 70px) to (100vw, 100vh)

```css
.dashboard-main {
    margin-left: 280px;
    margin-top: 70px;
    padding: 24px;
    min-height: calc(100vh - 70px);
    background: #ffffff;
}
```

## Component Positioning

### Status Cards Row
- **Position**: Top of main content
- **Layout**: 4 cards in a row
- **Card dimensions**: Each card 25% width minus gutters
- **Coordinates**: (304px, 94px) to (calc(100vw - 24px), 180px)

```css
.status-overview {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 20px;
    margin-bottom: 32px;
}

.status-card {
    height: 120px;
    padding: 20px;
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 8px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
```

### Tool Panels Section
- **Position**: Below status cards
- **Layout**: 2-column grid
- **Left column**: Tool selection forms
- **Right column**: Results display
- **Coordinates**: (304px, 212px) to (calc(100vw - 24px), flexible height)

```css
.tool-panels {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 32px;
    margin-top: 32px;
}

.tool-panel {
    background: white;
    border: 1px solid #e5e7eb;
    border-radius: 12px;
    padding: 24px;
    min-height: 400px;
}

.results-panel {
    background: #1f2937;
    color: #f9fafb;
    font-family: 'Consolas', 'Monaco', monospace;
    padding: 24px;
    border-radius: 12px;
    overflow-y: auto;
    max-height: 600px;
}
```

## Navigation Structure

### Sidebar Menu Items
Each menu section follows this structure:

```css
.nav-section {
    margin-bottom: 32px;
}

.nav-section-title {
    font-size: 14px;
    font-weight: 600;
    color: #6b7280;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 12px;
    padding: 0 16px;
}

.nav-item {
    display: flex;
    align-items: center;
    padding: 12px 16px;
    margin: 4px 8px;
    border-radius: 8px;
    cursor: pointer;
    transition: all 0.2s ease;
}

.nav-item:hover {
    background: #e5e7eb;
}

.nav-item.active {
    background: #dbeafe;
    color: #1d4ed8;
    font-weight: 500;
}
```

## Form Layout Specifications

### Input Groups
- **Label**: Top-aligned, 14px font, 600 weight
- **Input**: Full width, 40px height, 12px padding
- **Spacing**: 20px between groups

```css
.form-group {
    margin-bottom: 20px;
}

.form-label {
    display: block;
    font-size: 14px;
    font-weight: 600;
    color: #374151;
    margin-bottom: 8px;
}

.form-input {
    width: 100%;
    height: 40px;
    padding: 0 12px;
    border: 1px solid #d1d5db;
    border-radius: 6px;
    font-size: 14px;
    transition: border-color 0.2s ease;
}

.form-input:focus {
    outline: none;
    border-color: #2563eb;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.1);
}
```

### Button Styling
- **Primary**: Blue gradient, white text
- **Secondary**: Gray border, dark text
- **Height**: 40px
- **Padding**: 0 20px

```css
.btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    height: 40px;
    padding: 0 20px;
    border-radius: 6px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.2s ease;
    border: none;
}

.btn-primary {
    background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%);
    color: white;
}

.btn-primary:hover {
    background: linear-gradient(135deg, #1d4ed8 0%, #1e40af 100%);
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
}

.btn-secondary {
    background: white;
    border: 1px solid #d1d5db;
    color: #374151;
}

.btn-secondary:hover {
    background: #f9fafb;
    border-color: #9ca3af;
}
```

## Responsive Breakpoints

### Large Desktop (1920px+)
```css
@media (min-width: 1920px) {
    .dashboard-main {
        max-width: 1600px;
        margin-left: auto;
        margin-right: auto;
        padding-left: 280px;
    }
}
```

### Standard Desktop (1366px - 1919px)
```css
@media (min-width: 1366px) and (max-width: 1919px) {
    .tool-panels {
        grid-template-columns: 1fr 1fr;
    }
    
    .status-overview {
        grid-template-columns: repeat(4, 1fr);
    }
}
```

### Small Desktop (1200px - 1365px)
```css
@media (min-width: 1200px) and (max-width: 1365px) {
    .dashboard-sidebar {
        width: 240px;
    }
    
    .dashboard-main {
        margin-left: 240px;
    }
    
    .status-overview {
        grid-template-columns: repeat(2, 1fr);
    }
}
```

## Color Palette

### Primary Colors
```css
:root {
    --primary-50: #eff6ff;
    --primary-100: #dbeafe;
    --primary-500: #3b82f6;
    --primary-600: #2563eb;
    --primary-700: #1d4ed8;
    --primary-900: #1e3a8a;
}
```

### Neutral Colors
```css
:root {
    --gray-50: #f9fafb;
    --gray-100: #f3f4f6;
    --gray-200: #e5e7eb;
    --gray-300: #d1d5db;
    --gray-400: #9ca3af;
    --gray-500: #6b7280;
    --gray-600: #4b5563;
    --gray-700: #374151;
    --gray-800: #1f2937;
    --gray-900: #111827;
}
```

### Status Colors
```css
:root {
    --success: #10b981;
    --warning: #f59e0b;
    --error: #ef4444;
    --info: #3b82f6;
}
```

## Typography Scale

```css
:root {
    --font-family-sans: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    --font-family-mono: 'Consolas', 'Monaco', 'Courier New', monospace;
}

.text-xs { font-size: 12px; line-height: 16px; }
.text-sm { font-size: 14px; line-height: 20px; }
.text-base { font-size: 16px; line-height: 24px; }
.text-lg { font-size: 18px; line-height: 28px; }
.text-xl { font-size: 20px; line-height: 28px; }
.text-2xl { font-size: 24px; line-height: 32px; }
.text-3xl { font-size: 30px; line-height: 36px; }
```

## Implementation Checklist

### Phase 1: Structure
- [ ] Implement fixed header bar
- [ ] Create fixed sidebar navigation  
- [ ] Set up main content area with proper margins
- [ ] Add responsive grid system

### Phase 2: Components
- [ ] Build status cards row
- [ ] Create tool panels layout
- [ ] Implement results display area
- [ ] Add form styling

### Phase 3: Interactions
- [ ] Navigation active states
- [ ] Button hover effects
- [ ] Form focus states
- [ ] Loading indicators

### Phase 4: Responsiveness  
- [ ] Test on 1920x1080 resolution
- [ ] Verify 1366x768 compatibility
- [ ] Ensure 1200px minimum works
- [ ] Mobile fallback (optional)

## Testing Coordinates

Use these specific coordinates to verify layout positioning:

1. **Header Logo**: (20px, 20px) from top-left
2. **Sidebar First Item**: (16px, 90px) from page top-left  
3. **Status Card 1**: (304px, 94px) from page top-left
4. **Main Content**: (304px, 94px) starting position
5. **Results Panel**: Right column of tool panels grid

This guide ensures consistent, professional layout implementation across all screen sizes while maintaining the desktop-first approach requested for server environments.
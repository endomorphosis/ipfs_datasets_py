
// Performance Optimization Utilities

class PerformanceOptimizer {
    constructor() {
        this.intersectionObserver = null;
        this.setupLazyLoading();
        this.setupVirtualScrolling();
        this.setupCaching();
    }
    
    setupLazyLoading() {
        // Lazy load dashboard components
        this.intersectionObserver = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    this.loadComponent(entry.target);
                    this.intersectionObserver.unobserve(entry.target);
                }
            });
        }, { rootMargin: '50px' });
        
        document.querySelectorAll('[data-lazy-load]').forEach(el => {
            this.intersectionObserver.observe(el);
        });
    }
    
    loadComponent(element) {
        const componentType = element.dataset.lazyLoad;
        
        // Show loading skeleton
        element.innerHTML = '<div class="loading-skeleton" style="height: 200px;"></div>';
        
        // Simulate component loading
        setTimeout(() => {
            switch(componentType) {
                case 'chart':
                    this.loadChart(element);
                    break;
                case 'table':
                    this.loadTable(element);
                    break;
                default:
                    element.innerHTML = '<p>Component loaded!</p>';
            }
        }, Math.random() * 1000 + 500);
    }
    
    loadChart(element) {
        element.innerHTML = `
            <div class="chart-placeholder">
                <canvas width="400" height="200" style="background: #f0f0f0;"></canvas>
                <p>Chart visualization loaded</p>
            </div>
        `;
    }
    
    loadTable(element) {
        element.innerHTML = `
            <table class="data-table">
                <thead>
                    <tr><th>Column 1</th><th>Column 2</th><th>Column 3</th></tr>
                </thead>
                <tbody>
                    <tr><td>Data 1</td><td>Data 2</td><td>Data 3</td></tr>
                    <tr><td>Data 4</td><td>Data 5</td><td>Data 6</td></tr>
                </tbody>
            </table>
        `;
    }
    
    setupVirtualScrolling() {
        // Virtual scrolling for large datasets
        document.querySelectorAll('[data-virtual-scroll]').forEach(container => {
            this.enableVirtualScrolling(container);
        });
    }
    
    enableVirtualScrolling(container) {
        const itemHeight = parseInt(container.dataset.itemHeight) || 50;
        const items = JSON.parse(container.dataset.items || '[]');
        let scrollTop = 0;
        let visibleStart = 0;
        let visibleEnd = 10;
        
        container.style.height = '400px';
        container.style.overflow = 'auto';
        
        const render = () => {
            const visibleItems = items.slice(visibleStart, visibleEnd);
            container.innerHTML = visibleItems.map(item => 
                `<div style="height: ${itemHeight}px; padding: 10px; border-bottom: 1px solid #eee;">${item}</div>`
            ).join('');
        };
        
        container.addEventListener('scroll', () => {
            scrollTop = container.scrollTop;
            visibleStart = Math.floor(scrollTop / itemHeight);
            visibleEnd = visibleStart + 10;
            render();
        });
        
        render();
    }
    
    setupCaching() {
        // Simple cache for API responses
        this.cache = new Map();
        this.cacheExpiry = new Map();
        
        // Override fetch for caching
        const originalFetch = window.fetch;
        window.fetch = (...args) => {
            const url = args[0];
            const cacheKey = typeof url === 'string' ? url : url.url;
            
            // Check cache
            if (this.cache.has(cacheKey) && Date.now() < this.cacheExpiry.get(cacheKey)) {
                return Promise.resolve(new Response(JSON.stringify(this.cache.get(cacheKey))));
            }
            
            return originalFetch(...args).then(response => {
                if (response.ok) {
                    const clone = response.clone();
                    clone.json().then(data => {
                        this.cache.set(cacheKey, data);
                        this.cacheExpiry.set(cacheKey, Date.now() + 5 * 60 * 1000); // 5 minutes
                    });
                }
                return response;
            });
        };
    }
    
    // Bundle size optimization
    loadModuleOnDemand(moduleName) {
        return new Promise((resolve, reject) => {
            const script = document.createElement('script');
            script.src = `/static/modules/${moduleName}.js`;
            script.onload = () => resolve(window[moduleName]);
            script.onerror = reject;
            document.head.appendChild(script);
        });
    }
    
    // Memory cleanup
    cleanup() {
        if (this.intersectionObserver) {
            this.intersectionObserver.disconnect();
        }
        this.cache.clear();
        this.cacheExpiry.clear();
    }
}

// Initialize performance optimizer
document.addEventListener('DOMContentLoaded', () => {
    window.performanceOptimizer = new PerformanceOptimizer();
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (window.performanceOptimizer) {
        window.performanceOptimizer.cleanup();
    }
});

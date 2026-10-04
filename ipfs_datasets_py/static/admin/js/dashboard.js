// Dashboard JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Initialize charts
    initCharts();

    // Set up log filtering
    setupLogFilter();

    // Set up page navigation
    setupNavigation();
});

function initCharts() {
    // CPU chart
    const cpuCtx = document.getElementById('cpuChart').getContext('2d');
    const cpuChart = new Chart(cpuCtx, {
        type: 'line',
        data: {
            labels: Array.from({length: 10}, (_, i) => i),
            datasets: [{
                label: 'CPU Usage (%)',
                data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                backgroundColor: 'rgba(75, 192, 192, 0.2)',
                borderColor: 'rgba(75, 192, 192, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });

    // Memory chart
    const memoryCtx = document.getElementById('memoryChart').getContext('2d');
    const memoryChart = new Chart(memoryCtx, {
        type: 'line',
        data: {
            labels: Array.from({length: 10}, (_, i) => i),
            datasets: [{
                label: 'Memory Usage (%)',
                data: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                backgroundColor: 'rgba(153, 102, 255, 0.2)',
                borderColor: 'rgba(153, 102, 255, 1)',
                borderWidth: 1
            }]
        },
        options: {
            scales: {
                y: {
                    beginAtZero: true,
                    max: 100
                }
            }
        }
    });

    // In a real implementation, we would fetch data periodically
}

function setupLogFilter() {
    const logFilter = document.getElementById('logFilter');
    if (!logFilter) return;

    logFilter.addEventListener('input', function() {
        const filterText = this.value.toLowerCase();
        const logEntries = document.querySelectorAll('.log-entry');

        logEntries.forEach(entry => {
            const text = entry.textContent.toLowerCase();
            if (text.includes(filterText)) {
                entry.style.display = '';
            } else {
                entry.style.display = 'none';
            }
        });
    });
}

function setupNavigation() {
    // Smooth scrolling for anchor links
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        anchor.addEventListener('click', function(e) {
            e.preventDefault();
            document.querySelector(this.getAttribute('href')).scrollIntoView({
                behavior: 'smooth'
            });
        });
    });

    // Highlight current section in sidebar
    window.addEventListener('scroll', highlightCurrentSection);
}

function highlightCurrentSection() {
    const sections = document.querySelectorAll('section');
    const navLinks = document.querySelectorAll('.nav-link');

    let currentSection = '';

    sections.forEach(section => {
        const sectionTop = section.offsetTop;
        const sectionHeight = section.clientHeight;

        if (window.pageYOffset >= sectionTop - 100) {
            currentSection = section.getAttribute('id');
        }
    });

    navLinks.forEach(link => {
        link.classList.remove('active');
        if (link.getAttribute('href') === `#${currentSection}`) {
            link.classList.add('active');
        }
    });
}

// Fetch updated data from API periodically
function fetchUpdatedData() {
    // In a real implementation, we would fetch updates from API endpoints
    // and update the charts and tables
}
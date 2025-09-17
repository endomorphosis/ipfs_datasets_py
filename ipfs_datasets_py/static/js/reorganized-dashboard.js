/**
 * Reorganized MCP Dashboard with Queue Management
 * 
 * This dashboard provides comprehensive queue management and control
 * interface for the IPFS Datasets MCP server.
 * 
 * Features:
 * - Real-time queue status monitoring
 * - Task management and control
 * - Queue operations and administration
 * - Interactive task execution
 * 
 * @version 1.0.0
 */

class ReorganizedDashboard {
    constructor(mcpSDK) {
        this.sdk = mcpSDK;
        this.isInitialized = false;
        this.updateInterval = null;
        
        // Bind methods
        this.refreshQueueStatus = this.refreshQueueStatus.bind(this);
        this.refreshTasks = this.refreshTasks.bind(this);
        this.handleTaskAction = this.handleTaskAction.bind(this);
        
        // Initialize when DOM is ready
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', () => this.init());
        } else {
            this.init();
        }
    }

    /**
     * Initialize the dashboard
     */
    async init() {
        if (this.isInitialized) return;
        
        try {
            console.log('Initializing Reorganized Dashboard...');
            
            // Set up event listeners
            this.setupEventListeners();
            
            // Create queue management UI if it doesn't exist
            this.createQueueManagementUI();
            
            // Start periodic updates
            this.startPeriodicUpdates();
            
            // Initial data load
            await this.refreshAll();
            
            this.isInitialized = true;
            console.log('Reorganized Dashboard initialized successfully');
            
        } catch (error) {
            console.error('Failed to initialize dashboard:', error);
            this.showError('Failed to initialize dashboard: ' + error.message);
        }
    }

    /**
     * Set up event listeners
     */
    setupEventListeners() {
        // SDK event listeners
        this.sdk.on('queueStatusUpdate', (status) => {
            this.updateQueueStatus(status);
        });
        
        this.sdk.on('tasksUpdate', (tasks) => {
            this.updateTasksList(tasks);
        });
        
        // UI event listeners
        document.addEventListener('click', (e) => {
            if (e.target.matches('.task-action-btn')) {
                this.handleTaskAction(e);
            }
            
            if (e.target.matches('.refresh-queue-btn')) {
                this.refreshQueueStatus();
            }
            
            if (e.target.matches('.queue-task-btn')) {
                this.showQueueTaskModal();
            }
        });
    }

    /**
     * Create queue management UI components
     */
    createQueueManagementUI() {
        // Check if queue section already exists
        if (document.getElementById('queue-management-section')) {
            return;
        }
        
        const container = document.querySelector('.container-fluid') || document.body;
        
        const queueSection = document.createElement('div');
        queueSection.id = 'queue-management-section';
        queueSection.className = 'row mb-4';
        queueSection.innerHTML = `
            <div class="col-12">
                <div class="card shadow-sm">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">
                            <i class="fa-solid fa-list-check"></i> Queue Management
                        </h5>
                        <div>
                            <button class="btn btn-primary btn-sm queue-task-btn">
                                <i class="fa-solid fa-plus"></i> Queue Task
                            </button>
                            <button class="btn btn-outline-secondary btn-sm refresh-queue-btn">
                                <i class="fa-solid fa-refresh"></i> Refresh
                            </button>
                        </div>
                    </div>
                    <div class="card-body">
                        <!-- Queue Status -->
                        <div class="row mb-3" id="queue-status-cards">
                            <div class="col-md-2">
                                <div class="card bg-primary text-white">
                                    <div class="card-body text-center">
                                        <div class="h4 mb-0" id="queue-length">0</div>
                                        <small>Queued</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-2">
                                <div class="card bg-warning text-white">
                                    <div class="card-body text-center">
                                        <div class="h4 mb-0" id="active-tasks">0</div>
                                        <small>Active</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-2">
                                <div class="card bg-success text-white">
                                    <div class="card-body text-center">
                                        <div class="h4 mb-0" id="completed-tasks">0</div>
                                        <small>Completed</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-2">
                                <div class="card bg-danger text-white">
                                    <div class="card-body text-center">
                                        <div class="h4 mb-0" id="failed-tasks">0</div>
                                        <small>Failed</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-2">
                                <div class="card bg-info text-white">
                                    <div class="card-body text-center">
                                        <div class="h4 mb-0" id="max-concurrent">5</div>
                                        <small>Max Concurrent</small>
                                    </div>
                                </div>
                            </div>
                            <div class="col-md-2">
                                <div class="card bg-secondary text-white">
                                    <div class="card-body text-center">
                                        <div class="badge badge-light" id="queue-status">Running</div>
                                        <small class="d-block">Status</small>
                                    </div>
                                </div>
                            </div>
                        </div>
                        
                        <!-- Tasks List -->
                        <div class="row">
                            <div class="col-12">
                                <ul class="nav nav-tabs" id="tasks-tabs">
                                    <li class="nav-item">
                                        <a class="nav-link active" data-toggle="tab" href="#queued-tasks">
                                            Queued (<span id="queued-count">0</span>)
                                        </a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" data-toggle="tab" href="#active-tasks-tab">
                                            Active (<span id="active-count">0</span>)
                                        </a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" data-toggle="tab" href="#completed-tasks-tab">
                                            Completed (<span id="completed-count">0</span>)
                                        </a>
                                    </li>
                                    <li class="nav-item">
                                        <a class="nav-link" data-toggle="tab" href="#failed-tasks-tab">
                                            Failed (<span id="failed-count">0</span>)
                                        </a>
                                    </li>
                                </ul>
                                
                                <div class="tab-content" id="tasks-content">
                                    <div class="tab-pane fade show active" id="queued-tasks">
                                        <div class="task-list" id="queued-tasks-list">
                                            <div class="text-center text-muted p-4">No queued tasks</div>
                                        </div>
                                    </div>
                                    <div class="tab-pane fade" id="active-tasks-tab">
                                        <div class="task-list" id="active-tasks-list">
                                            <div class="text-center text-muted p-4">No active tasks</div>
                                        </div>
                                    </div>
                                    <div class="tab-pane fade" id="completed-tasks-tab">
                                        <div class="task-list" id="completed-tasks-list">
                                            <div class="text-center text-muted p-4">No completed tasks</div>
                                        </div>
                                    </div>
                                    <div class="tab-pane fade" id="failed-tasks-tab">
                                        <div class="task-list" id="failed-tasks-list">
                                            <div class="text-center text-muted p-4">No failed tasks</div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Insert after header or at beginning
        const headerRow = container.querySelector('.row');
        if (headerRow) {
            headerRow.insertAdjacentElement('afterend', queueSection);
        } else {
            container.insertBefore(queueSection, container.firstChild);
        }
    }

    /**
     * Refresh queue status
     */
    async refreshQueueStatus() {
        try {
            console.log('Refreshing queue status...');
            const status = await this.sdk.getQueueStatus();
            this.updateQueueStatus(status);
        } catch (error) {
            console.error('❌ Queue status refresh failed:', error);
            this.showError('Queue status refresh failed: ' + error.message);
        }
    }

    /**
     * Refresh tasks list
     */
    async refreshTasks() {
        try {
            console.log('Refreshing tasks...');
            const tasks = await this.sdk.getQueueTasks();
            this.updateTasksList(tasks);
        } catch (error) {
            console.error('Tasks refresh failed:', error);
            this.showError('Tasks refresh failed: ' + error.message);
        }
    }

    /**
     * Refresh all data
     */
    async refreshAll() {
        await Promise.all([
            this.refreshQueueStatus(),
            this.refreshTasks()
        ]);
    }

    /**
     * Update queue status display
     */
    updateQueueStatus(status) {
        console.log('Updating queue status:', status);
        
        const elements = {
            'queue-length': status.queue_length || 0,
            'active-tasks': status.active_tasks || 0,
            'completed-tasks': status.completed_tasks || 0,
            'failed-tasks': status.failed_tasks || 0,
            'max-concurrent': status.max_concurrent || 5
        };
        
        for (const [id, value] of Object.entries(elements)) {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = value;
            }
        }
        
        // Update queue status badge
        const statusElement = document.getElementById('queue-status');
        if (statusElement) {
            statusElement.textContent = status.queue_paused ? 'Paused' : 'Running';
            statusElement.className = `badge ${status.queue_paused ? 'badge-warning' : 'badge-success'}`;
        }
    }

    /**
     * Update tasks list display
     */
    updateTasksList(tasks) {
        console.log('Updating tasks list:', tasks);
        
        const taskTypes = ['queued', 'active', 'completed', 'failed'];
        
        taskTypes.forEach(type => {
            const listElement = document.getElementById(`${type}-tasks-list`);
            const countElement = document.getElementById(`${type}-count`);
            
            if (!listElement || !countElement) return;
            
            const taskList = tasks[type] || [];
            countElement.textContent = taskList.length;
            
            if (taskList.length === 0) {
                listElement.innerHTML = `<div class="text-center text-muted p-4">No ${type} tasks</div>`;
                return;
            }
            
            const tasksHTML = taskList.map(task => this.renderTask(task, type)).join('');
            listElement.innerHTML = tasksHTML;
        });
    }

    /**
     * Render a single task
     */
    renderTask(task, type) {
        const statusClass = {
            'queued': 'primary',
            'running': 'warning', 
            'active': 'warning',
            'completed': 'success',
            'failed': 'danger',
            'cancelled': 'secondary'
        }[task.status || type] || 'secondary';
        
        const actions = this.getTaskActions(task, type);
        
        return `
            <div class="card mb-2">
                <div class="card-body p-3">
                    <div class="row align-items-center">
                        <div class="col-md-8">
                            <h6 class="mb-1">
                                ${task.tool_name || 'Unknown Tool'}
                                <span class="badge badge-${statusClass} ml-2">${task.status || type}</span>
                            </h6>
                            <small class="text-muted">
                                Category: ${task.category || 'unknown'} | 
                                ID: ${task.id} |
                                Created: ${task.created_time ? new Date(task.created_time).toLocaleString() : 'Unknown'}
                            </small>
                            ${task.error ? `<div class="text-danger small mt-1">Error: ${task.error}</div>` : ''}
                        </div>
                        <div class="col-md-4 text-right">
                            ${actions}
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * Get available actions for a task
     */
    getTaskActions(task, type) {
        const actions = [];
        
        if (type === 'queued' || type === 'active') {
            actions.push(`
                <button class="btn btn-sm btn-outline-danger task-action-btn" 
                        data-action="cancel" data-task-id="${task.id}">
                    <i class="fa-solid fa-times"></i> Cancel
                </button>
            `);
        }
        
        actions.push(`
            <button class="btn btn-sm btn-outline-info task-action-btn" 
                    data-action="details" data-task-id="${task.id}">
                <i class="fa-solid fa-info"></i> Details
            </button>
        `);
        
        return actions.join(' ');
    }

    /**
     * Handle task actions
     */
    async handleTaskAction(event) {
        const action = event.target.dataset.action;
        const taskId = event.target.dataset.taskId;
        
        try {
            switch (action) {
                case 'cancel':
                    await this.cancelTask(taskId);
                    break;
                case 'details':
                    await this.showTaskDetails(taskId);
                    break;
            }
        } catch (error) {
            console.error(`Failed to ${action} task:`, error);
            this.showError(`Failed to ${action} task: ${error.message}`);
        }
    }

    /**
     * Cancel a task
     */
    async cancelTask(taskId) {
        if (!confirm('Are you sure you want to cancel this task?')) {
            return;
        }
        
        const result = await this.sdk.cancelTask(taskId);
        this.showSuccess(result.message);
        await this.refreshAll();
    }

    /**
     * Show task details
     */
    async showTaskDetails(taskId) {
        const task = await this.sdk.getTaskDetails(taskId);
        
        // Create modal or detailed view
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">Task Details: ${task.id}</h5>
                        <button type="button" class="close" data-dismiss="modal">
                            <span>&times;</span>
                        </button>
                    </div>
                    <div class="modal-body">
                        <pre>${JSON.stringify(task, null, 2)}</pre>
                    </div>
                </div>
            </div>
        `;
        
        document.body.appendChild(modal);
        $(modal).modal('show');
        
        // Clean up modal after hiding
        $(modal).on('hidden.bs.modal', function() {
            document.body.removeChild(modal);
        });
    }

    /**
     * Show queue task modal
     */
    showQueueTaskModal() {
        // Implementation for queuing new tasks
        alert('Queue Task functionality - to be implemented');
    }

    /**
     * Start periodic updates
     */
    startPeriodicUpdates() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
        }
        
        this.updateInterval = setInterval(() => {
            this.refreshAll().catch(error => {
                console.warn('Periodic update failed:', error);
            });
        }, 5000); // Update every 5 seconds
    }

    /**
     * Stop periodic updates
     */
    stopPeriodicUpdates() {
        if (this.updateInterval) {
            clearInterval(this.updateInterval);
            this.updateInterval = null;
        }
    }

    /**
     * Show error message
     */
    showError(message) {
        console.error(message);
        
        // Try to find an alert container or create one
        let alertContainer = document.getElementById('alert-container');
        if (!alertContainer) {
            alertContainer = document.createElement('div');
            alertContainer.id = 'alert-container';
            alertContainer.className = 'position-fixed';
            alertContainer.style.cssText = 'top: 20px; right: 20px; z-index: 9999;';
            document.body.appendChild(alertContainer);
        }
        
        const alert = document.createElement('div');
        alert.className = 'alert alert-danger alert-dismissible fade show';
        alert.innerHTML = `
            ${message}
            <button type="button" class="close" data-dismiss="alert">
                <span>&times;</span>
            </button>
        `;
        
        alertContainer.appendChild(alert);
        
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            if (alert.parentNode) {
                alert.parentNode.removeChild(alert);
            }
        }, 5000);
    }

    /**
     * Show success message
     */
    showSuccess(message) {
        console.log(message);
        
        let alertContainer = document.getElementById('alert-container');
        if (!alertContainer) {
            alertContainer = document.createElement('div');
            alertContainer.id = 'alert-container';
            alertContainer.className = 'position-fixed';
            alertContainer.style.cssText = 'top: 20px; right: 20px; z-index: 9999;';
            document.body.appendChild(alertContainer);
        }
        
        const alert = document.createElement('div');
        alert.className = 'alert alert-success alert-dismissible fade show';
        alert.innerHTML = `
            ${message}
            <button type="button" class="close" data-dismiss="alert">
                <span>&times;</span>
            </button>
        `;
        
        alertContainer.appendChild(alert);
        
        setTimeout(() => {
            if (alert.parentNode) {
                alert.parentNode.removeChild(alert);
            }
        }, 3000);
    }

    /**
     * Destroy the dashboard
     */
    destroy() {
        this.stopPeriodicUpdates();
        this.sdk.stopPolling();
        this.isInitialized = false;
    }
}

// Export for both module and global usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ReorganizedDashboard;
} else {
    window.ReorganizedDashboard = ReorganizedDashboard;
}
// Chorus Dashboard Enhancements
(function() {
    'use strict';

    // Keyboard shortcuts
    function setupKeyboardShortcuts() {
        document.addEventListener('keydown', function(e) {
            // Ctrl/Cmd + Enter in any input/textarea submits the closest form
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                const target = e.target;
                if (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA') {
                    e.preventDefault();
                    const form = target.closest('form');
                    if (form) {
                        // Trigger htmx if it's an htmx-enabled button
                        const submitBtn = form.querySelector('button[type="submit"], button.btn-primary');
                        if (submitBtn) {
                            submitBtn.click();
                        } else {
                            form.requestSubmit();
                        }
                    }
                }
            }
        });

        // Auto-focus on new task input when page loads
        const newTaskInput = document.querySelector('.new-task-panel input[name="title"]');
        if (newTaskInput) {
            newTaskInput.focus();
        }
    }

    // Auto-scroll terminal iframe to bottom
    function setupTerminalAutoScroll() {
        const terminalIframes = document.querySelectorAll('.terminal-iframe');
        terminalIframes.forEach(iframe => {
            // Try to scroll to bottom after iframe loads
            iframe.addEventListener('load', function() {
                try {
                    // Note: This may not work due to same-origin policy
                    // ttyd handles scrolling internally
                    console.log('Terminal iframe loaded');
                } catch (e) {
                    // Expected due to cross-origin restrictions
                }
            });
        });
    }

    // Enhanced loading states
    function setupLoadingStates() {
        // Add visual feedback for htmx requests
        document.addEventListener('htmx:beforeRequest', function(evt) {
            const target = evt.detail.elt;
            if (target.classList.contains('btn')) {
                target.setAttribute('data-original-text', target.textContent);
                target.textContent = 'Loading...';
                target.disabled = true;
            }
        });

        document.addEventListener('htmx:afterRequest', function(evt) {
            const target = evt.detail.elt;
            if (target.classList.contains('btn')) {
                const originalText = target.getAttribute('data-original-text');
                if (originalText) {
                    target.textContent = originalText;
                    target.removeAttribute('data-original-text');
                }
                target.disabled = false;
            }
        });

        // Also handle errors to re-enable button
        document.addEventListener('htmx:responseError', function(evt) {
            const target = evt.detail.elt;
            if (target.classList.contains('btn')) {
                const originalText = target.getAttribute('data-original-text');
                if (originalText) {
                    target.textContent = originalText;
                    target.removeAttribute('data-original-text');
                }
                target.disabled = false;
            }
        });

        // Show success flash on successful requests
        document.addEventListener('htmx:afterOnLoad', function(evt) {
            if (evt.detail.successful && evt.detail.xhr.status === 200) {
                // Clear send message form after successful send
                if (evt.detail.elt.classList.contains('send-form')) {
                    const messageInput = evt.detail.elt.querySelector('input[name="message"]');
                    if (messageInput) {
                        messageInput.value = '';
                    }
                }
            }
        });
    }

    // Task search/filter
    function setupTaskSearch() {
        // Add search input to task panel header
        const taskPanel = document.querySelector('.task-panel .panel-header');
        if (taskPanel && !document.getElementById('task-search')) {
            const searchInput = document.createElement('input');
            searchInput.id = 'task-search';
            searchInput.type = 'text';
            searchInput.placeholder = 'Search tasks...';
            searchInput.className = 'task-search-input';

            const filterTabs = taskPanel.querySelector('.filter-tabs');
            if (filterTabs) {
                taskPanel.insertBefore(searchInput, filterTabs);
            }

            // Real-time search filter
            searchInput.addEventListener('input', function(e) {
                const searchTerm = e.target.value.toLowerCase();
                const taskItems = document.querySelectorAll('.task-item');

                taskItems.forEach(item => {
                    const title = item.querySelector('.task-title')?.textContent.toLowerCase() || '';
                    const stack = item.querySelector('.task-stack')?.textContent.toLowerCase() || '';
                    const matches = title.includes(searchTerm) || stack.includes(searchTerm);

                    item.style.display = matches ? 'block' : 'none';
                });
            });
        }
    }

    // Initialize on DOM ready
    function init() {
        setupKeyboardShortcuts();
        setupTerminalAutoScroll();
        setupLoadingStates();
        setupTaskSearch();

        // Re-run setup after htmx swaps
        document.addEventListener('htmx:afterSwap', function() {
            setupTerminalAutoScroll();
            setupTaskSearch();
        });
    }

    // Run init when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();

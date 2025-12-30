// Theme toggle functionality
(function() {
    // Get saved theme from localStorage or default to 'dark'
    const savedTheme = localStorage.getItem('theme') || 'dark';

    // Apply the saved theme on page load
    if (savedTheme === 'light') {
        document.documentElement.setAttribute('data-theme', 'light');
    }

    // Theme toggle function
    function toggleTheme() {
        const root = document.documentElement;
        const currentTheme = root.getAttribute('data-theme');
        const newTheme = currentTheme === 'light' ? 'dark' : 'light';

        if (newTheme === 'light') {
            root.setAttribute('data-theme', 'light');
        } else {
            root.removeAttribute('data-theme');
        }

        // Save preference to localStorage
        localStorage.setItem('theme', newTheme);
    }

    // Attach event listener when DOM is ready
    const button = document.getElementById('theme-toggle-btn');
    if (button) {
        button.addEventListener('click', toggleTheme);
    }

    // Also expose globally for backward compatibility
    window.toggleTheme = toggleTheme;
})();

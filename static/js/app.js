// State management
let currentUser = null;
let tickers = [];
let sources = {
    sellside: [],
    substack: []
};
let themes = [];
let settings = {};

// Login functionality
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const statusEl = document.getElementById('login-status');

    try {
        const response = await fetch('/api/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password })
        });

        const data = await response.json();

        if (data.status === 'success') {
            currentUser = username;
            document.getElementById('analyst-name').textContent = `Welcome, ${username}`;
            document.getElementById('login-screen').style.display = 'none';
            document.getElementById('dashboard').style.display = 'block';

            // Load user data
            loadUserData();
        } else {
            statusEl.textContent = 'Invalid credentials';
            statusEl.className = 'error';
        }
    } catch (error) {
        statusEl.textContent = 'Error: ' + error.message;
        statusEl.className = 'error';
    }
});

// Logout
document.getElementById('logout-btn').addEventListener('click', () => {
    currentUser = null;
    document.getElementById('login-screen').style.display = 'block';
    document.getElementById('dashboard').style.display = 'none';
    document.getElementById('login-form').reset();
});

// Tab switching
document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabName = btn.dataset.tab;

        // Update tab buttons
        document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        // Update tab content
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        document.getElementById(`${tabName}-tab`).classList.add('active');
    });
});

// Ticker Management
document.getElementById('ticker-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const ticker = document.getElementById('ticker-input').value.trim().toUpperCase();

    if (ticker && !tickers.includes(ticker)) {
        try {
            const response = await fetch('/api/tickers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ticker })
            });

            const data = await response.json();

            if (data.status === 'success') {
                tickers.push(ticker);
                renderTickers();
                document.getElementById('ticker-input').value = '';
            }
        } catch (error) {
            console.error('Error adding ticker:', error);
        }
    }
});

function renderTickers() {
    const list = document.getElementById('ticker-list');

    if (tickers.length === 0) {
        list.innerHTML = '<p style="color: #999;">No tickers added yet</p>';
        return;
    }

    list.innerHTML = tickers.map(ticker => `
        <div class="item">
            <div class="item-content">
                <div class="item-title">${ticker}</div>
            </div>
            <div class="item-actions">
                <button class="btn-delete" onclick="deleteTicker('${ticker}')">Remove</button>
            </div>
        </div>
    `).join('');
}

async function deleteTicker(ticker) {
    try {
        await fetch(`/api/tickers/${ticker}`, { method: 'DELETE' });
        tickers = tickers.filter(t => t !== ticker);
        renderTickers();
    } catch (error) {
        console.error('Error deleting ticker:', error);
    }
}

// Sell-Side Source Management
document.getElementById('sellside-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const source = {
        bank: document.getElementById('sellside-bank').value,
        portalUrl: document.getElementById('sellside-portal-url').value,
        username: document.getElementById('sellside-username').value,
        password: document.getElementById('sellside-password').value
    };

    try {
        const response = await fetch('/api/sources/sellside', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(source)
        });

        const data = await response.json();

        if (data.status === 'success') {
            sources.sellside.push({ ...source, id: data.id });
            renderSellSideSources();
            document.getElementById('sellside-form').reset();
        }
    } catch (error) {
        console.error('Error adding sell-side source:', error);
    }
});

function renderSellSideSources() {
    const list = document.getElementById('sellside-list');

    if (sources.sellside.length === 0) {
        list.innerHTML = '<p style="color: #999;">No sell-side sources added yet</p>';
        return;
    }

    list.innerHTML = sources.sellside.map(source => `
        <div class="item">
            <div class="item-content">
                <div class="item-title">${source.bank.toUpperCase()}</div>
                <div class="item-details">${source.portalUrl}</div>
                <div class="item-details">Username: ${source.username}</div>
            </div>
            <div class="item-actions">
                <button class="btn-delete" onclick="deleteSellSideSource('${source.id}')">Remove</button>
            </div>
        </div>
    `).join('');
}

async function deleteSellSideSource(id) {
    try {
        await fetch(`/api/sources/sellside/${id}`, { method: 'DELETE' });
        sources.sellside = sources.sellside.filter(s => s.id !== id);
        renderSellSideSources();
    } catch (error) {
        console.error('Error deleting sell-side source:', error);
    }
}

// Substack Source Management
document.getElementById('substack-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const source = {
        name: document.getElementById('substack-name').value,
        url: document.getElementById('substack-url').value,
        hasRss: document.getElementById('substack-has-rss').checked,
        requiresLogin: document.getElementById('substack-requires-login').checked
    };

    try {
        const response = await fetch('/api/sources/substack', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(source)
        });

        const data = await response.json();

        if (data.status === 'success') {
            sources.substack.push({ ...source, id: data.id });
            renderSubstackSources();
            document.getElementById('substack-form').reset();
        }
    } catch (error) {
        console.error('Error adding substack source:', error);
    }
});

function renderSubstackSources() {
    const list = document.getElementById('substack-list');

    if (sources.substack.length === 0) {
        list.innerHTML = '<p style="color: #999;">No Substack sources added yet</p>';
        return;
    }

    list.innerHTML = sources.substack.map(source => `
        <div class="item">
            <div class="item-content">
                <div class="item-title">${source.name}</div>
                <div class="item-details">${source.url}</div>
                <div class="item-details">
                    ${source.hasRss ? '✓ Has RSS' : '✗ No RSS'} •
                    ${source.requiresLogin ? '🔒 Login Required' : '🔓 Public'}
                </div>
            </div>
            <div class="item-actions">
                <button class="btn-delete" onclick="deleteSubstackSource('${source.id}')">Remove</button>
            </div>
        </div>
    `).join('');
}

async function deleteSubstackSource(id) {
    try {
        await fetch(`/api/sources/substack/${id}`, { method: 'DELETE' });
        sources.substack = sources.substack.filter(s => s.id !== id);
        renderSubstackSources();
    } catch (error) {
        console.error('Error deleting substack source:', error);
    }
}

// Theme Management
document.getElementById('theme-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const theme = {
        name: document.getElementById('theme-name').value,
        keywords: document.getElementById('theme-keywords').value,
        priority: document.getElementById('theme-priority').value
    };

    try {
        const response = await fetch('/api/themes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(theme)
        });

        const data = await response.json();

        if (data.status === 'success') {
            themes.push({ ...theme, id: data.id });
            renderThemes();
            document.getElementById('theme-form').reset();
        }
    } catch (error) {
        console.error('Error adding theme:', error);
    }
});

function renderThemes() {
    const list = document.getElementById('theme-list');

    if (themes.length === 0) {
        list.innerHTML = '<p style="color: #999;">No themes added yet</p>';
        return;
    }

    list.innerHTML = themes.map(theme => `
        <div class="item">
            <div class="item-content">
                <div class="item-title">${theme.name}</div>
                <div class="item-details">Keywords: ${theme.keywords}</div>
                <div class="item-details">
                    <span class="priority-${theme.priority}">${theme.priority.toUpperCase()} Priority</span>
                </div>
            </div>
            <div class="item-actions">
                <button class="btn-delete" onclick="deleteTheme('${theme.id}')">Remove</button>
            </div>
        </div>
    `).join('');
}

async function deleteTheme(id) {
    try {
        await fetch(`/api/themes/${id}`, { method: 'DELETE' });
        themes = themes.filter(t => t.id !== id);
        renderThemes();
    } catch (error) {
        console.error('Error deleting theme:', error);
    }
}

// Settings Management
document.getElementById('settings-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const settings = {
        emailRecipient: document.getElementById('email-recipient').value,
        emailCC: document.getElementById('email-cc').value,
        briefingTime: document.getElementById('briefing-time').value,
        timezone: document.getElementById('timezone').value,
        skipWeekends: document.getElementById('skip-weekends').checked,
        openaiKey: document.getElementById('openai-key').value
    };

    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });

        const data = await response.json();

        const statusEl = document.getElementById('action-status');
        if (data.status === 'success') {
            statusEl.textContent = 'Settings saved successfully!';
            statusEl.className = 'success';
        } else {
            statusEl.textContent = 'Error saving settings';
            statusEl.className = 'error';
        }
    } catch (error) {
        const statusEl = document.getElementById('action-status');
        statusEl.textContent = 'Error: ' + error.message;
        statusEl.className = 'error';
    }
});

// Manual Actions
document.getElementById('test-briefing-btn').addEventListener('click', async () => {
    const statusEl = document.getElementById('action-status');
    statusEl.textContent = 'Generating test briefing...';
    statusEl.className = 'success';

    try {
        const response = await fetch('/api/generate-briefing', { method: 'POST' });
        const data = await response.json();

        if (data.status === 'success') {
            statusEl.textContent = 'Test briefing generated! Check your console for output.';
            console.log('Briefing:', data.briefing);
        } else {
            statusEl.textContent = 'Error generating briefing: ' + data.message;
            statusEl.className = 'error';
        }
    } catch (error) {
        statusEl.textContent = 'Error: ' + error.message;
        statusEl.className = 'error';
    }
});

document.getElementById('test-email-btn').addEventListener('click', async () => {
    const statusEl = document.getElementById('action-status');
    statusEl.textContent = 'Sending test email...';
    statusEl.className = 'success';

    try {
        const response = await fetch('/api/test-email', { method: 'POST' });
        const data = await response.json();

        if (data.status === 'success') {
            statusEl.textContent = 'Test email sent successfully!';
        } else {
            statusEl.textContent = 'Error sending email: ' + data.message;
            statusEl.className = 'error';
        }
    } catch (error) {
        statusEl.textContent = 'Error: ' + error.message;
        statusEl.className = 'error';
    }
});

// Load user data on dashboard load
async function loadUserData() {
    try {
        const response = await fetch('/api/user-data');
        const data = await response.json();

        if (data.status === 'success') {
            tickers = data.tickers || [];
            sources = data.sources || { sellside: [], substack: [] };
            themes = data.themes || [];
            settings = data.settings || {};

            renderTickers();
            renderSellSideSources();
            renderSubstackSources();
            renderThemes();

            // Populate settings form
            if (settings.emailRecipient) {
                document.getElementById('email-recipient').value = settings.emailRecipient;
            }
            if (settings.briefingTime) {
                document.getElementById('briefing-time').value = settings.briefingTime;
            }
            if (settings.timezone) {
                document.getElementById('timezone').value = settings.timezone;
            }
        }
    } catch (error) {
        console.error('Error loading user data:', error);
    }
}

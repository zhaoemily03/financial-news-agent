// Login functionality
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = document.getElementById('username').value;
    const password = document.getElementById('password').value;
    const statusEl = document.getElementById('login-status');

    try {
        const response = await fetch('/login', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ username, password })
        });

        const data = await response.json();

        if (data.status === 'success') {
            statusEl.textContent = data.message;
            statusEl.className = 'success';
        } else {
            statusEl.textContent = 'Login failed';
            statusEl.className = 'error';
        }
    } catch (error) {
        statusEl.textContent = 'Error: ' + error.message;
        statusEl.className = 'error';
    }
});

// Single article summarization
document.getElementById('single-article-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const url = document.getElementById('article-url').value;
    const resultContainer = document.getElementById('single-result');
    const submitBtn = e.target.querySelector('button');

    // Show loading state
    submitBtn.textContent = 'Processing...';
    submitBtn.disabled = true;
    resultContainer.innerHTML = '<p>Fetching article...</p>';
    resultContainer.classList.add('active');

    try {
        // Fetch article
        const fetchResponse = await fetch('/fetch-article', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ url })
        });

        const fetchData = await fetchResponse.json();

        if (fetchData.status === 'success') {
            resultContainer.innerHTML = '<p>Summarizing...</p>';

            // Summarize article
            const summaryResponse = await fetch('/summarize', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ content: fetchData.content })
            });

            const summaryData = await summaryResponse.json();

            if (summaryData.status === 'success') {
                resultContainer.innerHTML = `
                    <h3>Summary</h3>
                    <p><strong>URL:</strong> <a href="${url}" target="_blank" class="result-url">${url}</a></p>
                    <p>${summaryData.summary}</p>
                `;
            } else {
                resultContainer.innerHTML = `<p style="color: red;">Error: ${summaryData.message}</p>`;
            }
        } else {
            resultContainer.innerHTML = `<p style="color: red;">Error: ${fetchData.message}</p>`;
        }
    } catch (error) {
        resultContainer.innerHTML = `<p style="color: red;">Error: ${error.message}</p>`;
    } finally {
        submitBtn.textContent = 'Fetch & Summarize';
        submitBtn.disabled = false;
    }
});

// Batch article processing
document.getElementById('batch-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const urlsText = document.getElementById('batch-urls').value;
    const urls = urlsText.split('\n').filter(url => url.trim() !== '');
    const resultContainer = document.getElementById('batch-results');
    const submitBtn = e.target.querySelector('button');

    if (urls.length === 0) {
        alert('Please enter at least one URL');
        return;
    }

    // Show loading state
    submitBtn.textContent = 'Processing...';
    submitBtn.disabled = true;
    resultContainer.innerHTML = '<p>Processing articles...</p>';
    resultContainer.classList.add('active');

    const summaries = [];

    // Process each URL sequentially
    for (let i = 0; i < urls.length; i++) {
        const url = urls[i].trim();
        resultContainer.innerHTML = `<p>Processing ${i + 1} of ${urls.length}...</p>`;

        try {
            // Fetch article
            const fetchResponse = await fetch('/fetch-article', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ url })
            });

            const fetchData = await fetchResponse.json();

            if (fetchData.status === 'success') {
                // Summarize article
                const summaryResponse = await fetch('/summarize', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({ content: fetchData.content })
                });

                const summaryData = await summaryResponse.json();

                summaries.push({
                    url: url,
                    summary: summaryData.status === 'success' ? summaryData.summary : 'Error: ' + summaryData.message,
                    success: summaryData.status === 'success'
                });
            } else {
                summaries.push({
                    url: url,
                    summary: 'Error: ' + fetchData.message,
                    success: false
                });
            }
        } catch (error) {
            summaries.push({
                url: url,
                summary: 'Error: ' + error.message,
                success: false
            });
        }
    }

    // Display all results
    let resultsHTML = '<h3>Batch Results</h3>';
    summaries.forEach((item, index) => {
        resultsHTML += `
            <div class="result-item">
                <p><strong>Article ${index + 1}:</strong></p>
                <p><a href="${item.url}" target="_blank" class="result-url">${item.url}</a></p>
                <p style="color: ${item.success ? '#333' : 'red'};">${item.summary}</p>
            </div>
        `;
    });

    resultContainer.innerHTML = resultsHTML;
    submitBtn.textContent = 'Process All';
    submitBtn.disabled = false;
});

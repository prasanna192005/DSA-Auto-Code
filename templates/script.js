  const generateForm = document.getElementById('generate-form');
        const commitForm = document.getElementById('commit-form');
        const deleteForm = document.getElementById('delete-form');
        const verificationSection = document.getElementById('verification-section');
        const loader = document.getElementById('loader');
        const statusContainer = document.getElementById('status-message-container');
        const problemSelectorContainer = document.getElementById('problem-selector-container');
        const problemSelector = document.getElementById('problem-selector');
        const deleteBeltSelector = document.getElementById('delete-belt');
        const deleteProblemSelector = document.getElementById('delete-problem-folder');
        const deleteBtn = document.getElementById('delete-btn');
        const tabLinks = document.querySelectorAll('.tab-link');
        const tabPanels = document.querySelectorAll('.tab-panel');

        // ---GLOBAL STATE---
        let generatedProblems = [];

        // ---FUNCTIONS---
        function switchTab(e) {
            e.preventDefault();
            const targetTab = e.currentTarget.getAttribute('data-tab');
            tabLinks.forEach(link => link.classList.remove('active'));
            e.currentTarget.classList.add('active');
            tabPanels.forEach(panel => panel.classList.toggle('hidden', panel.id !== targetTab));
            statusContainer.innerHTML = '';
        }

        function populateVerificationForm(problemIndex) {
            const problem = generatedProblems[problemIndex];
            if (!problem) return;
            document.getElementById('problem_title').value = problem.title;
            document.getElementById('verify-topic').value = problem.topic;
            document.getElementById('readme_content').value = problem.readme;
            document.getElementById('solution_content').value = problem.solution;
        }
        
        async function fetchProblemsForBelt(beltName) {
            deleteProblemSelector.innerHTML = '<option value="">Loading...</option>';
            deleteProblemSelector.disabled = true;
            deleteBtn.disabled = true;
            const response = await fetch(`/problems/${beltName}`);
            if (response.ok) {
                const problems = await response.json();
                deleteProblemSelector.innerHTML = '';
                if (problems.length > 0) {
                    deleteProblemSelector.add(new Option('-- Select a problem --', '', true, true));
                    problems.forEach(problem => deleteProblemSelector.add(new Option(problem, problem)));
                    deleteProblemSelector.disabled = false;
                    deleteBtn.disabled = false;
                } else {
                    deleteProblemSelector.innerHTML = '<option value="">-- No problems found --</option>';
                }
            } else {
                deleteProblemSelector.innerHTML = '<option value="">-- Error loading --</option>';
            }
        }

        function toggleSchedule(isScheduled) {
            document.getElementById('schedule-section').classList.toggle('hidden', !isScheduled);
        }

        function displayMessage(message, type, duration = 4000) {
            const messageDiv = document.createElement('div');
            messageDiv.className = `status-message ${type}`;
            messageDiv.textContent = message;
            statusContainer.appendChild(messageDiv);
            setTimeout(() => { if (messageDiv) messageDiv.remove(); }, duration);
        }

        // ---EVENT LISTENERS---
        tabLinks.forEach(link => link.addEventListener('click', switchTab));
        problemSelector.addEventListener('change', (e) => populateVerificationForm(e.target.value));

        generateForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            loader.classList.remove('hidden');
            verificationSection.classList.add('hidden');
            problemSelectorContainer.classList.add('hidden');
            statusContainer.innerHTML = '';
            generateForm.querySelector('button').setAttribute('aria-busy', 'true');
            const formData = new FormData(generateForm);
            const response = await fetch('/generate', { method: 'POST', body: formData });
            loader.classList.add('hidden');
            generateForm.querySelector('button').removeAttribute('aria-busy');
            if (response.ok) {
                generatedProblems = await response.json();
                if (generatedProblems && generatedProblems.length > 0) {
                    problemSelector.innerHTML = '';
                    generatedProblems.forEach((p, i) => problemSelector.add(new Option(p.title || `Problem ${i + 1}`, i)));
                    problemSelectorContainer.classList.remove('hidden');
                    verificationSection.classList.remove('hidden');
                    document.getElementById('verify-belt').value = formData.get('belt');
                    populateVerificationForm(0);
                } else { 
                    const result = await response.json();
                    displayMessage(result.message || 'AI generated no problems.', 'error');
                }
            } else { displayMessage('Error generating problems. Check server console.', 'error'); }
        });

        commitForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            commitForm.querySelector('button').setAttribute('aria-busy', 'true');
            const formData = new FormData(commitForm);
            const response = await fetch('/commit', { method: 'POST', body: formData });
            commitForm.querySelector('button').removeAttribute('aria-busy');
            const result = await response.json();
            if (response.ok) {
                displayMessage(result.message, 'success');
                verificationSection.classList.add('hidden');
                problemSelectorContainer.classList.add('hidden');
                commitForm.reset();
            } else { displayMessage(result.message, 'error'); }
        });

        deleteBeltSelector.addEventListener('change', (e) => {
            const selectedBelt = e.target.value;
            if (selectedBelt) fetchProblemsForBelt(selectedBelt);
        });

        deleteForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            if (!confirm('Are you sure you want to permanently delete this problem from the repository?')) return;
            deleteBtn.setAttribute('aria-busy', 'true');
            const formData = new FormData(deleteForm);
            const response = await fetch('/delete', { method: 'POST', body: formData });
            deleteBtn.removeAttribute('aria-busy');
            const result = await response.json();
            if (response.ok) {
                displayMessage(result.message, 'success');
                fetchProblemsForBelt(deleteBeltSelector.value);
            } else { displayMessage(result.message, 'error'); }
        });
document.addEventListener('DOMContentLoaded', () => {
    // --- State ---
    let selectedPath = '';
    let filterMode = 'include';
    let historyData = [];

    // --- DOM Elements ---
    const navItems = document.querySelectorAll('.nav-item');
    const tabContents = document.querySelectorAll('.tab-content');
    
    // Dashboard Elements
    const selectedPathDisplay = document.getElementById('selected-path-display');
    const btnPickFolder = document.getElementById('btn-pick-folder');
    const btnPickFile = document.getElementById('btn-pick-file');
    const btnStart = document.getElementById('btn-start');
    const consoleOutput = document.getElementById('console-output');
    const progressVal = document.getElementById('progress-val');
    const statusSummary = document.getElementById('status-summary');
    const toggleBtns = document.querySelectorAll('.toggle-btn');
    
    // History & Settings Elements
    const historyList = document.getElementById('history-list');
    const btnSaveSettings = document.getElementById('btn-save-settings');

    // --- Tab Switching ---
    navItems.forEach(item => {
        item.onclick = () => {
            const targetTab = item.dataset.tab;
            navItems.forEach(i => i.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            item.classList.add('active');
            document.getElementById(`tab-${targetTab}`).classList.add('active');
            
            if (targetTab === 'history') loadHistory();
            if (targetTab === 'settings') loadSettings();
        };
    });

    // --- Initialize ---
    loadSettings(true); // Load settings and apply defaults to Dashboard

    // --- Native Pickers ---
    btnPickFolder.onclick = async () => {
        const resp = await fetch('/api/shell/pick-folder');
        const data = await resp.json();
        if (data.path) {
            selectedPath = data.path;
            selectedPathDisplay.textContent = selectedPath;
            selectedPathDisplay.classList.add('active');
            addLog(`已选择文件夹: ${selectedPath}`, 'info');
        }
    };

    btnPickFile.onclick = async () => {
        const resp = await fetch('/api/shell/pick-file');
        const data = await resp.json();
        if (data.path) {
            selectedPath = data.path;
            selectedPathDisplay.textContent = selectedPath;
            selectedPathDisplay.classList.add('active');
            addLog(`已选择文件: ${selectedPath}`, 'info');
        }
    };

    // --- Task Execution ---
    btnStart.onclick = startTask;

    toggleBtns.forEach(btn => {
        btn.onclick = () => {
            toggleBtns.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            filterMode = btn.dataset.mode;
        };
    });

    // --- Settings Logic ---
    async function loadSettings(applyToDashboard = false) {
        try {
            const resp = await fetch('/api/settings');
            const s = await resp.json();
            
            document.getElementById('set-default-suffixes').value = s.default_suffixes;
            document.getElementById('set-recursive-default').checked = s.recursive_default;
            document.getElementById('set-dryrun-default').checked = s.dry_run_default;
            document.getElementById('set-ignore-hidden').checked = s.ignore_hidden;

            if (applyToDashboard) {
                document.getElementById('suffix-list').value = s.default_suffixes;
                document.getElementById('recursive-check').checked = s.recursive_default;
                document.getElementById('dry-run-check').checked = s.dry_run_default;
            }
        } catch (e) {
            console.error('Failed to load settings', e);
        }
    }

    btnSaveSettings.onclick = async () => {
        const s = {
            default_suffixes: document.getElementById('set-default-suffixes').value,
            recursive_default: document.getElementById('set-recursive-default').checked,
            dry_run_default: document.getElementById('set-dryrun-default').checked,
            ignore_hidden: document.getElementById('set-ignore-hidden').checked
        };
        const resp = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(s)
        });
        if (resp.ok) alert('系统设置已保存');
    };

    // --- History Logic ---
    async function loadHistory() {
        historyList.innerHTML = '<tr><td colspan="5" style="text-align:center">正在加载...</td></tr>';
        try {
            const resp = await fetch('/api/history');
            historyData = await resp.json();
            renderHistory();
        } catch (e) {
            historyList.innerHTML = '<tr><td colspan="5" style="text-align:center; color:red">加载失败</td></tr>';
        }
    }

    function renderHistory() {
        historyList.innerHTML = '';
        if (historyData.length === 0) {
            historyList.innerHTML = '<tr><td colspan="5" style="text-align:center">暂无历史记录</td></tr>';
            return;
        }
        historyData.forEach(item => {
            const tr = document.createElement('tr');
            const shortPath = item.path.length > 40 ? '...' + item.path.slice(-37) : item.path;
            const mode = item.config.dry_run ? '<span style="color:var(--warning)">预览</span>' : '<span style="color:var(--success)">执行</span>';
            
            tr.innerHTML = `
                <td>${item.time}</td>
                <td title="${item.path}">${shortPath}</td>
                <td>${mode}</td>
                <td>${item.total}</td>
                <td><button class="btn-mini btn-reuse" data-id="${item.id}">复用参数</button></td>
            `;
            
            tr.querySelector('.btn-reuse').onclick = () => {
                reuseParams(item.config);
                navItems[0].click(); // Switch to dashboard
                addLog('已从历史记录中恢复任务参数', 'info');
            };
            
            historyList.appendChild(tr);
        });
    }

    function reuseParams(cfg) {
        selectedPath = cfg.path;
        selectedPathDisplay.textContent = selectedPath;
        document.getElementById('rename-pattern').value = cfg.rename_pattern || '';
        document.getElementById('rename-replace').value = cfg.rename_replace || '';
        document.getElementById('mtime-start').value = cfg.mtime.split(',')[0] || '';
        document.getElementById('mtime-end').value = cfg.mtime.split(',')[1] || '';
        document.getElementById('recursive-check').checked = cfg.recursive;
        document.getElementById('dry-run-check').checked = cfg.dry_run;
        
        if (cfg.include_exts) {
            document.getElementById('suffix-list').value = cfg.include_exts;
            toggleBtns[0].click();
        } else if (cfg.exclude_exts) {
            document.getElementById('suffix-list').value = cfg.exclude_exts;
            toggleBtns[1].click();
        }
    }

    // --- Task Execution ---
    async function startTask() {
        if (!selectedPath) {
            addLog('请先选择目标文件夹或文件！', 'warn');
            return;
        }

        const isDryRun = document.getElementById('dry-run-check').checked;
        const config = {
            path: selectedPath,
            recursive: document.getElementById('recursive-check').checked,
            rename_pattern: document.getElementById('rename-pattern').value,
            rename_replace: document.getElementById('rename-replace').value,
            mtime: document.getElementById('mtime-start').value + ',' + document.getElementById('mtime-end').value,
            dry_run: isDryRun,
            include_exts: filterMode === 'include' ? document.getElementById('suffix-list').value : '',
            exclude_exts: filterMode === 'exclude' ? document.getElementById('suffix-list').value : ''
        };

        btnStart.disabled = true;
        progressVal.textContent = '0%';
        progressVal.style.background = 'radial-gradient(circle, rgba(142,45,226,0.1) 0%, transparent 70%)';
        
        const modeLabel = isDryRun ? '【预览模式 - 不修改文件】' : '【正式执行 - 正在修改】';
        addLog(`--- 任务开始 ${modeLabel} ---`, isDryRun ? 'warn' : 'info');

        try {
            const response = await fetch('/api/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config)
            });

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                const chunk = decoder.decode(value);
                const lines = chunk.split('\n\n');

                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const data = JSON.parse(line.substring(6));
                            handleEvent(data);
                        } catch (e) {}
                    }
                }
            }
        } catch (e) {
            addLog(`请求失败: ${e.message}`, 'error');
        } finally {
            btnStart.disabled = false;
        }
    }

    function handleEvent(data) {
        switch (data.type) {
            case 'info':
                addLog(data.msg, 'info');
                statusSummary.textContent = data.msg;
                break;
            case 'progress':
                const percent = Math.round((data.current / data.total) * 100);
                progressVal.textContent = `${percent}%`;
                progressVal.style.background = `conic-gradient(var(--success) ${percent}%, transparent 0)`;
                statusSummary.textContent = `(${data.current}/${data.total}) ${data.file}`;
                addLog(data.msg, 'done');
                break;
            case 'warn': addLog(data.msg, 'warn'); break;
            case 'error':
                addLog(data.msg, 'error');
                statusSummary.textContent = '任务出错';
                break;
            case 'done':
                addLog(data.msg, 'info');
                statusSummary.textContent = data.msg;
                break;
        }
    }

    function addLog(msg, type) {
        const div = document.createElement('div');
        div.className = `log-item log-${type}`;
        const time = new Date().toLocaleTimeString();
        div.textContent = `[${time}] ${msg}`;
        consoleOutput.appendChild(div);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    }
});

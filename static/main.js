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
    const progressVal = document.getElementById('progress-val');
    const statusSummary = document.getElementById('status-summary');
    const toggleBtns = document.querySelectorAll('.toggle-btn');
    
    // Stats Elements
    const statRenamed = document.getElementById('stat-renamed');
    const statTs = document.getElementById('stat-ts');
    const statTotal = document.getElementById('stat-total');

    // Mod Toggles
    const modNameCheck = document.getElementById('mod-name-check');
    const modMtimeCheck = document.getElementById('mod-mtime-check');
    const modAtimeCheck = document.getElementById('mod-atime-check');
    const modCtimeCheck = document.getElementById('mod-ctime-check');
    
    // History & Settings Elements
    const historyList = document.getElementById('history-list');
    const btnSaveSettings = document.getElementById('btn-save-settings');

    // Modal Elements
    const logModal = document.getElementById('log-modal');
    const closeModal = document.getElementById('close-modal');
    const modalLogContent = document.getElementById('modal-log-content');

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
    loadSettings(true); 

    // --- Native Pickers ---
    btnPickFolder.onclick = async () => {
        const resp = await fetch('/api/shell/pick-folder');
        const data = await resp.json();
        if (data.path) {
            selectedPath = data.path;
            selectedPathDisplay.textContent = selectedPath;
            selectedPathDisplay.classList.add('active');
        }
    };

    btnPickFile.onclick = async () => {
        const resp = await fetch('/api/shell/pick-file');
        const data = await resp.json();
        if (data.path) {
            selectedPath = data.path;
            selectedPathDisplay.textContent = selectedPath;
            selectedPathDisplay.classList.add('active');
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
            const shortPath = item.path.length > 35 ? '...' + item.path.slice(-32) : item.path;
            const mode = item.config.dry_run ? '<span style="color:var(--warning)">预览</span>' : '<span style="color:var(--success)">执行</span>';
            const stats = item.summary ? `${item.summary.renamed} / ${item.summary.ts_updated} / ${item.summary.total}` : `${item.total}`;

            tr.innerHTML = `
                <td>${item.time}</td>
                <td title="${item.path}">${shortPath}</td>
                <td>${mode}</td>
                <td>${stats}</td>
                <td>
                    <button class="btn-mini btn-details" style="background:var(--accent-primary)">详情</button>
                    <button class="btn-mini btn-reuse">复用</button>
                </td>
            `;
            
            tr.querySelector('.btn-reuse').onclick = () => {
                reuseParams(item.config);
                navItems[0].click(); 
                statusSummary.textContent = '已从历史记录中恢复任务参数';
            };

            tr.querySelector('.btn-details').onclick = () => {
                showLogModal(item.logs);
            };
            
            historyList.appendChild(tr);
        });
    }

    function showLogModal(logs) {
        modalLogContent.innerHTML = '';
        if (!logs || logs.length === 0) {
            modalLogContent.innerHTML = '<div style="color:var(--text-dim)">该任务暂无详细日志。</div>';
        } else {
            logs.forEach(log => {
                const div = document.createElement('div');
                div.className = 'log-line';
                div.textContent = log;
                modalLogContent.appendChild(div);
            });
        }
        logModal.classList.add('active');
    }

    closeModal.onclick = () => logModal.classList.remove('active');
    window.onclick = (e) => { if (e.target === logModal) logModal.classList.remove('active'); };

    function reuseParams(cfg) {
        selectedPath = cfg.path;
        selectedPathDisplay.textContent = selectedPath;
        document.getElementById('rename-pattern').value = cfg.rename_pattern || '';
        document.getElementById('rename-replace').value = cfg.rename_replace || '';
        document.getElementById('mtime-start').value = cfg.mtime ? cfg.mtime.split(',')[0] : '2025-01-01';
        document.getElementById('mtime-end').value = cfg.mtime ? cfg.mtime.split(',')[1] : '2025-12-31';
        document.getElementById('recursive-check').checked = cfg.recursive;
        document.getElementById('dry-run-check').checked = cfg.dry_run;
        
        // Match new toggles
        modNameCheck.checked = cfg.mod_name !== undefined ? cfg.mod_name : true;
        modMtimeCheck.checked = cfg.mod_mtime !== undefined ? cfg.mod_mtime : true;
        modAtimeCheck.checked = cfg.mod_atime !== undefined ? cfg.mod_atime : false;
        modCtimeCheck.checked = cfg.mod_ctime !== undefined ? cfg.mod_ctime : false;

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
            alert('请先选择目标路径！');
            return;
        }

        const isDryRun = document.getElementById('dry-run-check').checked;
        const config = {
            path: selectedPath,
            recursive: document.getElementById('recursive-check').checked,
            mod_name: modNameCheck.checked,
            mod_mtime: modMtimeCheck.checked,
            mod_atime: modAtimeCheck.checked,
            mod_ctime: modCtimeCheck.checked,
            rename_pattern: document.getElementById('rename-pattern').value,
            rename_replace: document.getElementById('rename-replace').value,
            mtime: document.getElementById('mtime-start').value + ',' + document.getElementById('mtime-end').value,
            dry_run: isDryRun,
            include_exts: filterMode === 'include' ? document.getElementById('suffix-list').value : '',
            exclude_exts: filterMode === 'exclude' ? document.getElementById('suffix-list').value : ''
        };

        btnStart.disabled = true;
        resetStats();
        
        const modeLabel = isDryRun ? '【预览模式】' : '【正式执行】';
        statusSummary.textContent = `任务启动中 ${modeLabel}...`;

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
            statusSummary.textContent = `请求失败: ${e.message}`;
        } finally {
            btnStart.disabled = false;
        }
    }

    function resetStats() {
        statRenamed.textContent = '0';
        statTs.textContent = '0';
        statTotal.textContent = '0 / 0';
        progressVal.textContent = '0%';
        progressVal.style.background = 'radial-gradient(circle, rgba(142,45,226,0.1) 0%, transparent 70%)';
    }

    function handleEvent(data) {
        switch (data.type) {
            case 'info':
                statusSummary.textContent = data.msg;
                break;
            case 'progress':
                const percent = Math.round((data.current / data.total) * 100);
                progressVal.textContent = `${percent}%`;
                progressVal.style.background = `conic-gradient(var(--success) ${percent}%, transparent 0)`;
                statRenamed.textContent = data.renamed_cnt;
                statTs.textContent = data.ts_cnt;
                statTotal.textContent = `${data.current} / ${data.total}`;
                break;
            case 'error':
                statusSummary.textContent = `错误: ${data.msg}`;
                break;
            case 'done':
                statusSummary.textContent = data.msg;
                break;
        }
    }
});

/**
 * RANDOM PICKER (GỌI TÊN NGẪU NHIÊN) ENGINE
 * Hỗ trợ 2 chế độ:
 * 1. 🎃 Gọi Tên Ngẫu Nhiên (Hiệu ứng kinh dị, âm thanh rùng rợn, đọc tên tiếng Việt)
 * 2. 🐎 Đua Ngựa (8 làn đua kịch tính, nước rút về đích, vinh danh người chiến thắng)
 * Tích hợp sâu vào hệ thống Điểm danh (scan.html) và Quản lý lớp học (index.html)
 */

class RandomPicker {
    constructor(options = {}) {
        this.container = typeof options.container === 'string' 
            ? document.querySelector(options.container) 
            : options.container;
        this.modalOverlay = typeof options.modalOverlay === 'string' 
            ? document.querySelector(options.modalOverlay) 
            : options.modalOverlay;
        
        this.title = options.title || 'GỌI TÊN NGẪU NHIÊN';
        this.subtitle = options.subtitle || '';
        this.isModal = !!options.isModal;
        this.onBonus = options.onBonus || null;
        this.onClose = options.onClose || null;

        // Sound & speech
        this.soundEnabled = true;
        this.audioContext = null;

        // Student lists
        this.allClassStudents = [];
        this.checkedInStudents = [];
        this.excelStudents = [];
        this.activeSource = 'checkedin'; // 'checkedin' | 'all' | 'excel'
        this.students = []; // Current active pool
        this.selectedStudents = []; // Students already picked [{maSV, fullName, time}]
        this.lastSelectedStudent = null;

        // State
        this.currentMode = 'picker'; // 'picker' | 'race'
        this.isSpinning = false;
        this.isRacing = false;
        this.raceAnimationInterval = null;
        this.raceParticipants = [];
        this.raceStartTime = 0;

        // Build DOM & Bind events
        this.initDOM();
        this.initEvents();

        // If initial students provided
        if (options.students && options.students.length > 0) {
            this.setStudents(options.students);
        }
    }

    // ============================================
    // DOM GENERATION
    // ============================================
    initDOM() {
        if (!this.container) return;

        this.container.innerHTML = `
            <div class="rp-fog"></div>
            <div class="rp-blood-drip"></div>
            <div class="rp-lightning-flash"></div>
            <div class="rp-horror-effects"></div>

            <div class="rp-container">
                <div class="rp-container-topbar">
                    ${this.isModal 
                        ? '<button class="rp-back-btn" id="rpBackBtn" title="Quay về màn hình điểm danh">⬅ Quay về Điểm danh</button>' 
                        : '<a href="scan.html" class="rp-back-btn" id="rpBackToScanLink" title="Quay về màn hình điểm danh">⬅ Quay về Điểm danh</a>'
                    }
                    <div class="rp-topbar-right">
                        <button class="rp-btn-icon" id="rpSoundToggle" title="Bật/Tắt âm thanh">🔊</button>
                        ${this.isModal ? '<button class="rp-btn-icon rp-btn-close" id="rpCloseBtn" title="Đóng (Esc)">&times;</button>' : ''}
                    </div>
                </div>

                <h1 class="rp-title">
                    <span class="rp-skull">💀</span>
                    ${this.title}
                    <span class="rp-skull">💀</span>
                </h1>
                <div class="rp-title-sub" id="rpSubTitle">${this.subtitle}</div>

                <!-- Mode Selection -->
                <div class="rp-mode-selector">
                    <button class="rp-mode-btn active" id="rpModePickerBtn">🎃 Gọi Tên Ngẫu Nhiên</button>
                    <button class="rp-mode-btn" id="rpModeRaceBtn">🐎 Đua Ngựa</button>
                </div>

                <!-- Source Selection Filter (Hiển thị khi tích hợp Điểm danh) -->
                <div class="rp-source-selector" id="rpSourceSelector" style="display: none;">
                    <span class="rp-source-label">Nguồn dữ liệu:</span>
                    <button class="rp-source-pill active" data-source="checkedin" id="rpSrcCheckedIn">✅ Đã vào lớp (0)</button>
                    <button class="rp-source-pill" data-source="all" id="rpSrcAll">👥 Cả lớp (0)</button>
                    <button class="rp-source-pill" data-source="excel" id="rpSrcExcel">📁 File Excel</button>
                </div>

                <!-- Class selector for standalone mode -->
                <div class="rp-class-select-box" id="rpClassSelectBox" style="display: none;">
                    <label style="font-size:13px; color:#94a3b8; font-weight:600;">Chọn lớp học:</label>
                    <select class="rp-class-select" id="rpClassSelect">
                        <option value="">-- Chọn lớp học từ CSDL --</option>
                    </select>
                </div>

                <!-- Excel Upload Section -->
                <div class="rp-upload-section" id="rpUploadSection" style="display: none;">
                    <label for="rpExcelFileInput" class="rp-upload-btn">
                        <span class="rp-ghost">👻</span> Tải File Excel <span class="rp-ghost">👻</span>
                    </label>
                    <input type="file" id="rpExcelFileInput" accept=".xlsx,.xls,.csv" hidden>
                    <p class="rp-hint">📋 Cột hỗ trợ: MSSV, Họ tên (hoặc MSSV, Họ, Tên)</p>
                </div>

                <!-- Student Counter -->
                <div class="rp-student-count" id="rpStudentCount">
                    🎃 Số linh hồn chờ triệu hồi: <strong>0</strong> / 0
                </div>

                <!-- ================= MODE 1: PICKER ================= -->
                <div id="rpPickerSection">
                    <div class="rp-name-display" id="rpNameDisplay">
                        <img class="rp-name-photo" id="rpNamePhoto" src="" alt="Sinh viên">
                        <div class="rp-name-mssv" id="rpNameMssv"></div>
                        <div class="rp-name-text" id="rpNameText">Chờ nạp danh sách...</div>
                    </div>

                    <div class="rp-actions-row">
                        <button class="rp-spin-btn" id="rpSpinBtn" disabled>
                            <span class="rp-bat">🦇</span> BẮT ĐẦU QUAY <span class="rp-bat">🦇</span>
                        </button>
                        <button class="rp-bonus-btn" id="rpQuickBonusBtn" style="display: none;">
                            🌟 Thưởng điểm
                        </button>
                        <button class="rp-reset-btn" id="rpResetBtn" title="Đặt lại danh sách gọi">
                            🔄 Làm mới lượt
                        </button>
                    </div>

                    <div class="rp-selected-list" id="rpSelectedList">
                        <h3>🕯️ Những Linh Hồn Được Chọn 🕯️</h3>
                        <ul id="rpSelectedNames"></ul>
                        <button class="rp-export-btn" id="rpExportBtn">
                            📥 Xuất Excel Danh Sách Đã Gọi
                        </button>
                    </div>
                </div>

                <!-- ================= MODE 2: RACE ================= -->
                <div class="rp-race-container" id="rpRaceSection" style="display: none;">
                    <div class="rp-race-info">
                        <h2>🏁 ĐUA NGỰA ĐOẠT MỆNH 🏁</h2>
                        <p id="rpRaceStatus">Nhấn nút để bắt đầu cuộc đua!</p>
                    </div>

                    <div class="rp-race-track" id="rpRaceTrack">
                        <div class="rp-finish-line"></div>
                        ${[0, 1, 2, 3, 4, 5, 6, 7].map(lane => `
                            <div class="rp-race-lane" data-lane="${lane}">
                                <div class="rp-horse-container">
                                    <div class="rp-horse-name"></div>
                                    <div class="rp-horse">${['🐎', '🐴', '🦄', '🐎', '🐴', '🦄', '🐎', '🐴'][lane]}</div>
                                </div>
                            </div>
                        `).join('')}
                    </div>

                    <button class="rp-race-btn" id="rpRaceBtn" disabled>
                        🏇 BẮT ĐẦU ĐUA
                    </button>
                </div>

                <div class="rp-bottom-bar">
                    ${this.isModal 
                        ? '<button class="rp-bottom-return-btn" id="rpBottomReturnBtn">⬅ Quay về màn hình Điểm danh</button>' 
                        : '<a href="scan.html" class="rp-bottom-return-btn" id="rpBottomReturnLink">📟 Quay về màn hình Điểm danh</a>'
                    }
                </div>
            </div>

            <!-- Winner Celebration Overlay -->
            <div class="rp-winner-overlay" id="rpWinnerOverlay">
                <div class="rp-winner-content">
                    <h1 class="rp-winner-title">🎊 CHIẾN THẮNG 🎊</h1>
                    <img class="rp-winner-photo" id="rpWinnerPhoto" src="" alt="">
                    <div class="rp-winner-name" id="rpWinnerName"></div>
                    <div class="rp-winner-mssv" id="rpWinnerMssv"></div>
                    <p class="rp-winner-subtitle">đã cán đích đầu tiên một cách xuất sắc!</p>
                    <div class="rp-winner-actions">
                        <button class="rp-bonus-btn" id="rpWinnerBonusBtn" style="display: none;">
                            🌟 Thưởng điểm chiến thắng
                        </button>
                        <button class="rp-continue-btn" id="rpWinnerContinueBtn">Tiếp tục</button>
                    </div>
                </div>
            </div>
        `;
    }

    initEvents() {
        if (!this.container) return;

        // Back buttons (return to attendance screen)
        const backBtn = this.container.querySelector('#rpBackBtn');
        if (backBtn) {
            backBtn.addEventListener('click', () => this.close());
        }

        const bottomReturnBtn = this.container.querySelector('#rpBottomReturnBtn');
        if (bottomReturnBtn) {
            bottomReturnBtn.addEventListener('click', () => this.close());
        }

        // Close button (for modal)
        const closeBtn = this.container.querySelector('#rpCloseBtn');
        if (closeBtn) {
            closeBtn.addEventListener('click', () => this.close());
        }

        // Close on clicking backdrop outside container
        if (this.modalOverlay) {
            this.modalOverlay.addEventListener('click', (e) => {
                if (e.target === this.modalOverlay) {
                    this.close();
                }
            });
        }

        // Sound toggle
        const soundBtn = this.container.querySelector('#rpSoundToggle');
        if (soundBtn) {
            soundBtn.addEventListener('click', () => {
                this.soundEnabled = !this.soundEnabled;
                soundBtn.textContent = this.soundEnabled ? '🔊' : '🔇';
                soundBtn.title = this.soundEnabled ? 'Đang bật âm thanh (nhấn để tắt)' : 'Đang tắt âm thanh (nhấn để bật)';
            });
        }

        // Mode buttons
        this.container.querySelector('#rpModePickerBtn').addEventListener('click', () => this.switchMode('picker'));
        this.container.querySelector('#rpModeRaceBtn').addEventListener('click', () => this.switchMode('race'));

        // Source pills
        this.container.querySelectorAll('.rp-source-pill').forEach(pill => {
            pill.addEventListener('click', (e) => {
                const src = e.currentTarget.dataset.source;
                this.setSource(src);
            });
        });

        // Excel file input
        const fileInput = this.container.querySelector('#rpExcelFileInput');
        if (fileInput) {
            fileInput.addEventListener('change', (e) => this.handleFileUpload(e));
        }

        // Spin button
        this.container.querySelector('#rpSpinBtn').addEventListener('click', () => this.startSpin());

        // Quick bonus button
        const quickBonusBtn = this.container.querySelector('#rpQuickBonusBtn');
        if (quickBonusBtn) {
            quickBonusBtn.addEventListener('click', () => {
                if (this.lastSelectedStudent && typeof this.onBonus === 'function') {
                    this.onBonus(this.lastSelectedStudent);
                }
            });
        }

        // Reset called pool
        this.container.querySelector('#rpResetBtn').addEventListener('click', () => {
            if (this.selectedStudents.length === 0) {
                this.showToast('ℹ️ Chưa có ai được gọi trong đợt này.');
                return;
            }
            if (confirm('Làm mới lại toàn bộ lượt gọi? (Các bạn đã gọi sẽ có thể được gọi lại)')) {
                this.selectedStudents = [];
                this.lastSelectedStudent = null;
                this.container.querySelector('#rpSelectedNames').innerHTML = '';
                this.container.querySelector('#rpSelectedList').classList.remove('show');
                this.updateUI(true);
                this.showToast('✅ Đã làm mới danh sách gọi!');
            }
        });

        // Export button
        this.container.querySelector('#rpExportBtn').addEventListener('click', () => this.exportToExcel());

        // Race button
        this.container.querySelector('#rpRaceBtn').addEventListener('click', () => this.startRace());

        // Winner overlay buttons
        this.container.querySelector('#rpWinnerContinueBtn').addEventListener('click', () => this.closeWinnerOverlay());
        const winnerBonusBtn = this.container.querySelector('#rpWinnerBonusBtn');
        if (winnerBonusBtn) {
            winnerBonusBtn.addEventListener('click', () => {
                if (this.lastSelectedStudent && typeof this.onBonus === 'function') {
                    this.onBonus(this.lastSelectedStudent);
                    this.closeWinnerOverlay();
                }
            });
        }

        // Class select dropdown (standalone)
        const classSelect = this.container.querySelector('#rpClassSelect');
        if (classSelect) {
            classSelect.addEventListener('change', (e) => {
                const classId = e.target.value;
                if (classId) {
                    this.loadClassFromAPI(classId);
                }
            });
        }

        // Keyboard ESC to close modal
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.isModal && this.modalOverlay && this.modalOverlay.classList.contains('active')) {
                this.close();
            }
        });
    }

    // ============================================
    // MODAL OPEN / CLOSE
    // ============================================
    open(data = {}) {
        if (this.modalOverlay) {
            this.modalOverlay.classList.add('active');
        }

        if (data.title) {
            this.container.querySelector('#rpSubTitle').innerHTML = `Lớp: <b>${data.title}</b>`;
        }

        // If session data provided (from scan.html)
        if (data.checkedIn || data.all) {
            this.checkedInStudents = data.checkedIn || [];
            this.allClassStudents = data.all || [];

            const srcSelector = this.container.querySelector('#rpSourceSelector');
            if (srcSelector) srcSelector.style.display = 'flex';

            this.updateSourcePills();

            // Default to checked-in if available, otherwise all
            if (this.checkedInStudents.length > 0) {
                this.setSource('checkedin');
            } else {
                this.setSource('all');
            }
        } else if (data.students) {
            this.setStudents(data.students);
        }

        this.initAudioContext();
    }

    close() {
        if (this.isSpinning || this.isRacing) {
            if (!confirm('Đang quay/đua, bạn có chắc muốn thoát?')) return;
        }

        if (this.raceAnimationInterval) {
            clearTimeout(this.raceAnimationInterval);
            this.isRacing = false;
        }

        if (this.modalOverlay) {
            this.modalOverlay.classList.remove('active');
        }

        if (typeof this.onClose === 'function') {
            this.onClose();
        }
    }

    // ============================================
    // DATA SOURCE MANAGEMENT
    // ============================================
    updateSourcePills() {
        const pIn = this.container.querySelector('#rpSrcCheckedIn');
        const pAll = this.container.querySelector('#rpSrcAll');
        if (pIn) pIn.textContent = `✅ Đã vào lớp (${this.checkedInStudents.length})`;
        if (pAll) pAll.textContent = `👥 Cả lớp (${this.allClassStudents.length})`;
    }

    setSource(source) {
        this.activeSource = source;
        this.container.querySelectorAll('.rp-source-pill').forEach(pill => {
            pill.classList.toggle('active', pill.dataset.source === source);
        });

        const uploadSection = this.container.querySelector('#rpUploadSection');

        if (source === 'checkedin') {
            if (uploadSection) uploadSection.style.display = 'none';
            this.setStudents(this.checkedInStudents);
        } else if (source === 'all') {
            if (uploadSection) uploadSection.style.display = 'none';
            this.setStudents(this.allClassStudents);
        } else if (source === 'excel') {
            if (uploadSection) uploadSection.style.display = 'block';
            this.setStudents(this.excelStudents);
        }
    }

    setStudents(studentList) {
        this.students = (studentList || []).map(s => ({
            maSV: s.maSV || s.student_id || '',
            ho: s.ho || s.last_name || '',
            ten: s.ten || s.first_name || '',
            fullName: s.fullName || s.full_name || `${s.ho || s.last_name || ''} ${s.ten || s.first_name || ''}`.trim(),
            photoUrl: s.photoUrl || (s.photo_path ? `/photos/${s.photo_path}` : '')
        }));

        this.updateUI(false);
        this.updateRaceUI();
    }

    async loadClassFromAPI(classId) {
        try {
            const res = await fetch(`/api/students?class_id=${encodeURIComponent(classId)}`);
            const data = await res.json();
            if (Array.isArray(data) && data.length > 0) {
                this.setStudents(data);
                this.showToast(`👻 Đã nạp ${data.length} sinh viên từ lớp ${classId}!`);
            } else {
                this.showToast('⚠️ Không có sinh viên trong lớp này!', 'error');
            }
        } catch (e) {
            console.error('Error loading class students:', e);
            this.showToast('⚠️ Lỗi tải danh sách sinh viên!', 'error');
        }
    }

    handleFileUpload(e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (evt) => {
            try {
                if (typeof XLSX === 'undefined') {
                    this.showToast('⚠️ Thư viện SheetJS chưa sẵn sàng!', 'error');
                    return;
                }

                const data = new Uint8Array(evt.target.result);
                const workbook = XLSX.read(data, { type: 'array' });
                const firstSheet = workbook.Sheets[workbook.SheetNames[0]];
                const jsonData = XLSX.utils.sheet_to_json(firstSheet, { header: 1 });

                if (!jsonData || jsonData.length < 2) {
                    this.showToast('⚠️ File rỗng hoặc không có dữ liệu!', 'error');
                    return;
                }

                // Detect headers
                const headerRow = jsonData[0].map(h => String(h || '').toLowerCase().trim());
                let colMSSV = headerRow.findIndex(h => h.includes('mssv') || h.includes('mã sv') || h.includes('ma sv'));
                let colHo = headerRow.findIndex(h => h === 'họ' || h === 'ho' || h.includes('họ đệm') || h.includes('ho dem'));
                let colTen = headerRow.findIndex(h => h === 'tên' || h === 'ten');
                let colFullName = headerRow.findIndex(h => h.includes('họ và tên') || h.includes('họ tên') || h.includes('hoten') || h.includes('full'));

                const parsed = [];
                for (let i = 1; i < jsonData.length; i++) {
                    const row = jsonData[i];
                    if (!row || row.length === 0) continue;

                    let maSV = '';
                    let ho = '';
                    let ten = '';
                    let fullName = '';

                    if (colMSSV !== -1) {
                        maSV = String(row[colMSSV] || '').trim();
                        if (colFullName !== -1) {
                            fullName = String(row[colFullName] || '').trim();
                        } else if (colHo !== -1 && colTen !== -1) {
                            ho = String(row[colHo] || '').trim();
                            ten = String(row[colTen] || '').trim();
                            fullName = `${ho} ${ten}`.trim();
                        }
                    } else if (row.length >= 3) {
                        maSV = String(row[0] || '').trim();
                        ho = String(row[1] || '').trim();
                        ten = String(row[2] || '').trim();
                        fullName = `${ho} ${ten}`.trim();
                    } else if (row.length === 2) {
                        maSV = String(row[0] || '').trim();
                        fullName = String(row[1] || '').trim();
                    } else if (row.length === 1) {
                        fullName = String(row[0] || '').trim();
                    }

                    if (fullName) {
                        parsed.push({ maSV, ho, ten, fullName, photoUrl: '' });
                    }
                }

                if (parsed.length > 0) {
                    this.excelStudents = parsed;
                    this.setStudents(parsed);
                    this.showToast(`👻 Đã triệu hồi ${parsed.length} linh hồn từ file Excel!`);
                } else {
                    this.showToast('⚠️ Không tìm thấy dữ liệu hợp lệ trong file!', 'error');
                }
            } catch (err) {
                console.error('Excel parse error:', err);
                this.showToast('⚠️ Lỗi khi đọc file Excel!', 'error');
            }
        };
        reader.readAsArrayBuffer(file);
    }

    // ============================================
    // AUDIO ENGINE (Web Audio API)
    // ============================================
    initAudioContext() {
        if (!this.audioContext) {
            const AudioCtx = window.AudioContext || window.webkitAudioContext;
            if (AudioCtx) {
                this.audioContext = new AudioCtx();
            }
        }
        if (this.audioContext && this.audioContext.state === 'suspended') {
            this.audioContext.resume();
        }
        return this.audioContext;
    }

    playSpinningSound() {
        if (!this.soundEnabled) return;
        try {
            const ctx = this.initAudioContext();
            if (!ctx) return;

            for (let i = 0; i < 20; i++) {
                setTimeout(() => {
                    if (!this.soundEnabled || !this.isSpinning) return;
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.connect(gain);
                    gain.connect(ctx.destination);

                    osc.type = 'square';
                    osc.frequency.value = 800 + Math.random() * 400;
                    gain.gain.value = 0.08;

                    osc.start();
                    osc.stop(ctx.currentTime + 0.05);
                }, i * 150);
            }
        } catch (e) {
            console.log('Spin sound error:', e);
        }
    }

    playHorrorScream() {
        if (!this.soundEnabled) return;
        try {
            const ctx = this.initAudioContext();
            if (!ctx) return;
            const now = ctx.currentTime;

            // 1. Scream Sawtooth (High to low)
            const screamOsc = ctx.createOscillator();
            const screamGain = ctx.createGain();
            screamOsc.connect(screamGain);
            screamGain.connect(ctx.destination);
            screamOsc.type = 'sawtooth';
            screamOsc.frequency.setValueAtTime(800, now);
            screamOsc.frequency.exponentialRampToValueAtTime(100, now + 1.5);
            screamGain.gain.setValueAtTime(0.35, now);
            screamGain.gain.exponentialRampToValueAtTime(0.01, now + 1.5);
            screamOsc.start(now);
            screamOsc.stop(now + 1.5);

            // 2. Moan Osc (Eerie sine)
            const moanOsc = ctx.createOscillator();
            const moanGain = ctx.createGain();
            moanOsc.connect(moanGain);
            moanGain.connect(ctx.destination);
            moanOsc.type = 'sine';
            moanOsc.frequency.setValueAtTime(150, now);
            moanOsc.frequency.setValueAtTime(120, now + 0.3);
            moanOsc.frequency.setValueAtTime(180, now + 0.6);
            moanOsc.frequency.setValueAtTime(100, now + 1);
            moanGain.gain.setValueAtTime(0.25, now);
            moanGain.gain.exponentialRampToValueAtTime(0.01, now + 2);
            moanOsc.start(now);
            moanOsc.stop(now + 2);

            // 3. Static White Noise
            const bufferSize = ctx.sampleRate * 1.5;
            const noiseBuffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
            const output = noiseBuffer.getChannelData(0);
            for (let i = 0; i < bufferSize; i++) {
                output[i] = Math.random() * 2 - 1;
            }
            const noise = ctx.createBufferSource();
            noise.buffer = noiseBuffer;
            const noiseGain = ctx.createGain();
            const noiseFilter = ctx.createBiquadFilter();
            noiseFilter.type = 'lowpass';
            noiseFilter.frequency.value = 500;
            noise.connect(noiseFilter);
            noiseFilter.connect(noiseGain);
            noiseGain.connect(ctx.destination);
            noiseGain.gain.setValueAtTime(0.12, now);
            noiseGain.gain.exponentialRampToValueAtTime(0.01, now + 1);
            noise.start(now);
            noise.stop(now + 1);

            // 4. Temple Bell Chime
            const bellOsc = ctx.createOscillator();
            const bellGain = ctx.createGain();
            bellOsc.connect(bellGain);
            bellGain.connect(ctx.destination);
            bellOsc.type = 'sine';
            bellOsc.frequency.value = 220;
            bellGain.gain.setValueAtTime(0.25, now);
            bellGain.gain.exponentialRampToValueAtTime(0.01, now + 2.5);
            bellOsc.start(now);
            bellOsc.stop(now + 2.5);

            // 5. Deep Bass Rumble
            const bassOsc = ctx.createOscillator();
            const bassGain = ctx.createGain();
            bassOsc.connect(bassGain);
            bassGain.connect(ctx.destination);
            bassOsc.type = 'sine';
            bassOsc.frequency.value = 55;
            bassGain.gain.setValueAtTime(0.4, now);
            bassGain.gain.exponentialRampToValueAtTime(0.01, now + 2);
            bassOsc.start(now);
            bassOsc.stop(now + 2);
        } catch (e) {
            console.log('Horror scream error:', e);
        }
    }

    playRaceSound() {
        if (!this.soundEnabled) return;
        try {
            const ctx = this.initAudioContext();
            if (!ctx) return;

            for (let i = 0; i < 30; i++) {
                setTimeout(() => {
                    if (!this.soundEnabled || !this.isRacing) return;
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.connect(gain);
                    gain.connect(ctx.destination);

                    osc.type = 'square';
                    osc.frequency.value = 100 + Math.random() * 50;
                    gain.gain.value = 0.05;

                    osc.start();
                    osc.stop(ctx.currentTime + 0.1);
                }, i * 300);
            }
        } catch (e) {
            console.log('Race sound error:', e);
        }
    }

    // ============================================
    // SPEECH SYNTHESIS (Đọc tên tiếng Việt)
    // ============================================
    speakName(name) {
        if (!this.soundEnabled || !('speechSynthesis' in window)) return;

        try {
            window.speechSynthesis.cancel();

            const speak = () => {
                const voices = window.speechSynthesis.getVoices();
                const utterance = new SpeechSynthesisUtterance(name);

                let selectedVoice = voices.find(v => v.lang.toLowerCase().startsWith('vi')) ||
                                    voices.find(v => v.name.toLowerCase().includes('vietnam') || v.name.toLowerCase().includes('vietnamese') || v.name.toLowerCase().includes('viet')) ||
                                    voices.find(v => v.name.includes('Huyen') || v.name.includes('An') || v.name.includes('HoaiMy'));

                if (selectedVoice) {
                    utterance.voice = selectedVoice;
                    utterance.lang = selectedVoice.lang;
                }

                utterance.rate = 0.9;
                utterance.pitch = 0.85;
                utterance.volume = 1;

                window.speechSynthesis.speak(utterance);
            };

            const voices = window.speechSynthesis.getVoices();
            if (voices.length === 0) {
                window.speechSynthesis.onvoiceschanged = speak;
                setTimeout(speak, 400);
            } else {
                speak();
            }
        } catch (e) {
            console.log('Speech error:', e);
        }
    }

    // ============================================
    // VISUAL EFFECTS
    // ============================================
    triggerLightning() {
        const flash = this.container.querySelector('.rp-lightning-flash');
        if (flash) {
            flash.classList.add('flash');
            setTimeout(() => flash.classList.remove('flash'), 220);
        }
    }

    triggerHorrorEffects() {
        const effects = this.container.querySelector('.rp-horror-effects');
        if (!effects) return;
        effects.innerHTML = '';

        // Blood drops
        for (let i = 0; i < 20; i++) {
            setTimeout(() => {
                const drop = document.createElement('div');
                drop.className = 'rp-blood-drop';
                drop.innerHTML = ['🩸', '💧', '❤️'][Math.floor(Math.random() * 3)];
                drop.style.left = Math.random() * 95 + 'vw';
                drop.style.animationDuration = (2 + Math.random() * 2) + 's';
                drop.style.fontSize = (1.4 + Math.random() * 1.4) + 'rem';
                effects.appendChild(drop);
                setTimeout(() => drop.remove(), 4000);
            }, i * 90);
        }

        // Floating skulls
        for (let i = 0; i < 6; i++) {
            const skull = document.createElement('div');
            skull.className = 'rp-floating-skull';
            skull.innerHTML = ['💀', '☠️', '👻', '🎃'][Math.floor(Math.random() * 4)];
            skull.style.left = Math.random() * 90 + 'vw';
            skull.style.top = Math.random() * 85 + 'vh';
            skull.style.animationDuration = (2.5 + Math.random() * 2) + 's';
            effects.appendChild(skull);
            setTimeout(() => skull.remove(), 5000);
        }

        // Bats
        for (let i = 0; i < 8; i++) {
            setTimeout(() => {
                const bat = document.createElement('div');
                bat.className = 'rp-flying-bat';
                bat.innerHTML = '🦇';
                bat.style.top = (10 + Math.random() * 65) + 'vh';
                bat.style.animationDuration = (1.2 + Math.random() * 1.8) + 's';
                effects.appendChild(bat);
                setTimeout(() => bat.remove(), 3000);
            }, i * 180);
        }

        setTimeout(() => { effects.innerHTML = ''; }, 5500);
    }

    createConfetti() {
        const overlay = this.container.querySelector('#rpWinnerOverlay');
        if (!overlay) return;
        const colors = ['#ffd700', '#ff6347', '#00ff00', '#ff1493', '#00bfff', '#fbbf24', '#a855f7'];

        for (let i = 0; i < 60; i++) {
            setTimeout(() => {
                const c = document.createElement('div');
                c.className = 'rp-confetti';
                c.style.left = Math.random() * 100 + '%';
                c.style.background = colors[Math.floor(Math.random() * colors.length)];
                c.style.animationDelay = (Math.random() * 1.5) + 's';
                overlay.appendChild(c);
                setTimeout(() => c.remove(), 3500);
            }, i * 40);
        }
    }

    showToast(message, type = 'success') {
        const toast = document.createElement('div');
        toast.className = `rp-notification ${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.style.animation = 'rpSlideDown 0.3s ease reverse';
            setTimeout(() => toast.remove(), 300);
        }, 3200);
    }

    // ============================================
    // MODE 1: GỌI TÊN NGẪU NHIÊN (SPINNER)
    // ============================================
    getAvailableStudents() {
        const selectedSet = new Set(this.selectedStudents.map(s => s.fullName));
        return this.students.filter(s => !selectedSet.has(s.fullName));
    }

    updateUI(resetName = true) {
        const available = this.getAvailableStudents();
        const total = this.students.length;

        const countEl = this.container.querySelector('#rpStudentCount');
        const spinBtn = this.container.querySelector('#rpSpinBtn');
        const nameText = this.container.querySelector('#rpNameText');
        const nameMssv = this.container.querySelector('#rpNameMssv');
        const namePhoto = this.container.querySelector('#rpNamePhoto');
        const quickBonusBtn = this.container.querySelector('#rpQuickBonusBtn');

        if (countEl) {
            countEl.innerHTML = `🎃 Số linh hồn chờ triệu hồi: <strong>${available.length}</strong> / ${total}`;
        }

        if (spinBtn) {
            spinBtn.disabled = available.length === 0;
        }

        if (resetName && !this.lastSelectedStudent) {
            if (nameText) {
                nameText.textContent = total === 0 
                    ? 'Chờ nạp danh sách...' 
                    : (available.length > 0 ? 'Nhấn để triệu hồi...' : 'Đã triệu hồi hết!');
                nameText.classList.remove('final', 'spinning');
            }
            if (nameMssv) nameMssv.classList.remove('show');
            if (namePhoto) namePhoto.classList.remove('show');
            if (quickBonusBtn) quickBonusBtn.style.display = 'none';
        }

        const selList = this.container.querySelector('#rpSelectedList');
        if (selList) {
            if (this.selectedStudents.length > 0) {
                selList.classList.add('show');
            } else {
                selList.classList.remove('show');
            }
        }
    }

    startSpin() {
        if (this.isSpinning) return;

        this.initAudioContext();

        const available = this.getAvailableStudents();
        if (available.length === 0) {
            this.showToast('⚠️ Đã hết linh hồn để triệu hồi trong đợt này!', 'error');
            return;
        }

        this.isSpinning = true;
        const spinBtn = this.container.querySelector('#rpSpinBtn');
        const nameText = this.container.querySelector('#rpNameText');
        const nameMssv = this.container.querySelector('#rpNameMssv');
        const namePhoto = this.container.querySelector('#rpNamePhoto');
        const quickBonusBtn = this.container.querySelector('#rpQuickBonusBtn');

        spinBtn.disabled = true;
        spinBtn.classList.add('spinning');
        nameText.classList.add('spinning');
        nameText.classList.remove('final');
        if (nameMssv) nameMssv.classList.remove('show');
        if (namePhoto) namePhoto.classList.remove('show');
        if (quickBonusBtn) quickBonusBtn.style.display = 'none';

        this.playSpinningSound();

        const totalDuration = 3000 + Math.random() * 1800;
        const startTime = Date.now();
        let currentSpeed = 50;
        const maxSpeed = 750;

        const easeOutQuart = (x) => 1 - Math.pow(1 - x, 4);

        const spinStep = () => {
            const elapsed = Date.now() - startTime;
            const progress = elapsed / totalDuration;

            if (progress < 1) {
                const randomStudent = available[Math.floor(Math.random() * available.length)];
                nameText.textContent = randomStudent.fullName;
                currentSpeed = 50 + (maxSpeed - 50) * easeOutQuart(progress);
                setTimeout(spinStep, currentSpeed);
            } else {
                this.finishSpin(available);
            }
        };

        spinStep();
    }

    finishSpin(available) {
        const selected = available[Math.floor(Math.random() * available.length)];
        this.selectedStudents.push({
            maSV: selected.maSV,
            fullName: selected.fullName,
            time: new Date().toLocaleTimeString('vi-VN')
        });
        this.lastSelectedStudent = selected;

        const nameText = this.container.querySelector('#rpNameText');
        const nameMssv = this.container.querySelector('#rpNameMssv');
        const namePhoto = this.container.querySelector('#rpNamePhoto');
        const quickBonusBtn = this.container.querySelector('#rpQuickBonusBtn');

        nameText.textContent = selected.fullName;
        nameText.classList.remove('spinning');
        nameText.classList.add('final');

        if (selected.maSV && nameMssv) {
            nameMssv.textContent = `MSSV: ${selected.maSV}`;
            nameMssv.classList.add('show');
        }

        if (selected.photoUrl && namePhoto) {
            namePhoto.src = selected.photoUrl;
            namePhoto.classList.add('show');
        }

        // Screen shake
        const rpContainer = this.container.querySelector('.rp-container');
        if (rpContainer) {
            rpContainer.classList.add('rp-screen-shake');
            setTimeout(() => rpContainer.classList.remove('rp-screen-shake'), 450);
        }

        this.triggerLightning();
        this.playHorrorScream();
        this.triggerHorrorEffects();

        // Speak student name after 800ms
        setTimeout(() => {
            this.speakName(selected.fullName);
        }, 800);

        // Show quick bonus button if bonus handler provided
        if (quickBonusBtn && typeof this.onBonus === 'function') {
            quickBonusBtn.style.display = 'inline-flex';
            quickBonusBtn.innerHTML = `🌟 Thưởng điểm cho ${selected.ten || selected.fullName}`;
        }

        // Add to selected list UI
        this.renderSelectedListItem(selected);

        // Enable button after cooldown
        setTimeout(() => {
            this.isSpinning = false;
            const spinBtn = this.container.querySelector('#rpSpinBtn');
            if (spinBtn) {
                spinBtn.classList.remove('spinning');
                const remaining = this.getAvailableStudents();
                spinBtn.disabled = remaining.length === 0;
            }
            this.updateUI(false);
        }, 2500);
    }

    renderSelectedListItem(student) {
        const ul = this.container.querySelector('#rpSelectedNames');
        if (!ul) return;

        const li = document.createElement('li');
        li.innerHTML = `
            <div class="rp-student-info">
                <span>💀</span>
                <span class="rp-student-mssv">[${student.maSV || 'N/A'}]</span>
                <strong>${student.fullName}</strong>
            </div>
            ${typeof this.onBonus === 'function' ? `
                <button class="rp-award-bonus-btn" title="Thưởng điểm cho sinh viên này">🌟 Thưởng điểm</button>
            ` : ''}
        `;

        const bonusBtn = li.querySelector('.rp-award-bonus-btn');
        if (bonusBtn && typeof this.onBonus === 'function') {
            bonusBtn.addEventListener('click', () => {
                this.onBonus(student);
            });
        }

        ul.insertBefore(li, ul.firstChild);
    }

    // ============================================
    // MODE 2: ĐUA NGỰA (HORSE RACE)
    // ============================================
    switchMode(mode) {
        this.currentMode = mode;
        const pickerBtn = this.container.querySelector('#rpModePickerBtn');
        const raceBtn = this.container.querySelector('#rpModeRaceBtn');
        const pickerSection = this.container.querySelector('#rpPickerSection');
        const raceSection = this.container.querySelector('#rpRaceSection');

        if (mode === 'picker') {
            pickerBtn.classList.add('active');
            raceBtn.classList.remove('active');
            pickerSection.style.display = '';
            raceSection.style.display = 'none';
        } else {
            pickerBtn.classList.remove('active');
            raceBtn.classList.add('active');
            pickerSection.style.display = 'none';
            raceSection.style.display = 'block';
            this.updateRaceUI();
        }
    }

    updateRaceUI() {
        const available = this.getAvailableStudents();
        const raceBtn = this.container.querySelector('#rpRaceBtn');
        const raceStatus = this.container.querySelector('#rpRaceStatus');

        if (available.length < 2) {
            if (raceBtn) raceBtn.disabled = true;
            if (raceStatus) raceStatus.textContent = `Cần ít nhất 2 sinh viên để đua! (Còn ${available.length} sinh viên)`;
        } else {
            if (raceBtn) raceBtn.disabled = false;
            if (raceStatus) raceStatus.textContent = `Sẵn sàng! Có ${available.length} sinh viên có thể tham gia đường đua.`;
        }
    }

    startRace() {
        if (this.isRacing) return;

        const available = this.getAvailableStudents();
        if (available.length < 2) {
            this.showToast('⚠️ Cần ít nhất 2 sinh viên để tổ chức đua!', 'error');
            return;
        }

        this.initAudioContext();

        // Pick up to 8 participants. If fewer than 8, duplicate or fill
        const shuffled = [...available].sort(() => Math.random() - 0.5);
        this.raceParticipants = [];
        for (let i = 0; i < 8; i++) {
            this.raceParticipants.push(shuffled[i % shuffled.length]);
        }

        // Setup lanes
        const lanes = this.container.querySelectorAll('.rp-race-lane');
        lanes.forEach((lane, idx) => {
            const container = lane.querySelector('.rp-horse-container');
            const nameDiv = lane.querySelector('.rp-horse-name');
            container.style.transition = 'none';
            container.style.left = '0%';
            nameDiv.textContent = this.raceParticipants[idx].fullName;
            container.dataset.position = 0;
        });

        this.isRacing = true;
        this.raceStartTime = Date.now();

        const raceBtn = this.container.querySelector('#rpRaceBtn');
        const raceStatus = this.container.querySelector('#rpRaceStatus');
        raceBtn.disabled = true;
        raceBtn.classList.add('racing');
        raceStatus.textContent = '🏇 Cuộc đua nghẹt thở đang diễn ra...';

        this.playRaceSound();
        this.animateRace();
    }

    animateRace() {
        const raceDuration = 9500;
        const finalSprintTime = 8000;
        const lanes = this.container.querySelectorAll('.rp-race-lane');
        const winnerIndex = Math.floor(Math.random() * 8);

        let horseBaseSpeeds = new Array(8).fill(0).map(() => 0.45 + Math.random() * 0.35);
        let lastSpeedChange = 0;

        const updateStep = () => {
            const elapsed = Date.now() - this.raceStartTime;

            if (elapsed >= raceDuration) {
                this.finishRace(winnerIndex);
                return;
            }

            if (elapsed - lastSpeedChange >= 1800) {
                horseBaseSpeeds = horseBaseSpeeds.map(() => 0.45 + Math.random() * 0.45);
                lastSpeedChange = elapsed;
            }

            lanes.forEach((lane, idx) => {
                const container = lane.querySelector('.rp-horse-container');
                let currentPos = parseFloat(container.dataset.position) || 0;

                let speed;
                if (elapsed >= finalSprintTime && idx === winnerIndex) {
                    speed = 1.8 + Math.random() * 1.0;
                } else if (elapsed >= finalSprintTime) {
                    speed = horseBaseSpeeds[idx] * 0.45 + Math.random() * 0.15;
                } else {
                    speed = horseBaseSpeeds[idx] + Math.random() * 0.25;
                }

                currentPos = Math.min(currentPos + speed, 89);
                container.dataset.position = currentPos;
                container.style.left = currentPos + '%';
            });

            this.raceAnimationInterval = setTimeout(updateStep, 95);
        };

        updateStep();
    }

    finishRace(winnerIndex) {
        clearTimeout(this.raceAnimationInterval);
        this.isRacing = false;

        const raceBtn = this.container.querySelector('#rpRaceBtn');
        if (raceBtn) {
            raceBtn.classList.remove('racing');
            raceBtn.disabled = false;
        }

        const winner = this.raceParticipants[winnerIndex];
        this.lastSelectedStudent = winner;

        // Animate winner crossing finish line
        const lanes = this.container.querySelectorAll('.rp-race-lane');
        const winnerContainer = lanes[winnerIndex].querySelector('.rp-horse-container');
        winnerContainer.style.transition = 'left 0.4s ease-out';
        winnerContainer.style.left = '92%';

        setTimeout(() => {
            this.playHorrorScream();
            this.showWinnerOverlay(winner);

            this.selectedStudents.push({
                maSV: winner.maSV,
                fullName: winner.fullName,
                time: new Date().toLocaleTimeString('vi-VN')
            });

            this.renderSelectedListItem({
                maSV: winner.maSV,
                fullName: `${winner.fullName} 🏆 (Vô địch đua ngựa)`
            });

            const selList = this.container.querySelector('#rpSelectedList');
            if (selList) selList.classList.add('show');
        }, 400);
    }

    showWinnerOverlay(winner) {
        const overlay = this.container.querySelector('#rpWinnerOverlay');
        const nameDiv = this.container.querySelector('#rpWinnerName');
        const mssvDiv = this.container.querySelector('#rpWinnerMssv');
        const photoImg = this.container.querySelector('#rpWinnerPhoto');
        const bonusBtn = this.container.querySelector('#rpWinnerBonusBtn');

        nameDiv.textContent = winner.fullName;
        if (winner.maSV && mssvDiv) {
            mssvDiv.textContent = `MSSV: ${winner.maSV}`;
            mssvDiv.style.display = 'block';
        } else if (mssvDiv) {
            mssvDiv.style.display = 'none';
        }

        if (winner.photoUrl && photoImg) {
            photoImg.src = winner.photoUrl;
            photoImg.classList.add('show');
        } else if (photoImg) {
            photoImg.classList.remove('show');
        }

        if (bonusBtn && typeof this.onBonus === 'function') {
            bonusBtn.style.display = 'inline-flex';
            bonusBtn.innerHTML = `🌟 Thưởng điểm cho ${winner.ten || winner.fullName}`;
        }

        overlay.classList.add('show');
        this.createConfetti();

        setTimeout(() => {
            this.speakName(`Chúc mừng ${winner.fullName} đã về đích đầu tiên`);
        }, 700);
    }

    closeWinnerOverlay() {
        const overlay = this.container.querySelector('#rpWinnerOverlay');
        if (overlay) overlay.classList.remove('show');
        this.updateRaceUI();
        this.updateUI(false);
    }

    // ============================================
    // EXCEL EXPORT
    // ============================================
    exportToExcel() {
        if (this.selectedStudents.length === 0) {
            this.showToast('⚠️ Chưa có linh hồn nào được triệu hồi!', 'error');
            return;
        }

        if (typeof XLSX === 'undefined') {
            this.showToast('⚠️ Thư viện SheetJS chưa sẵn sàng!', 'error');
            return;
        }

        try {
            const rows = [
                ['STT', 'Mã SV', 'Họ và Tên', 'Thời gian gọi']
            ];

            this.selectedStudents.forEach((item, idx) => {
                rows.push([
                    idx + 1,
                    item.maSV || '',
                    item.fullName,
                    item.time || ''
                ]);
            });

            const wb = XLSX.utils.book_new();
            const ws = XLSX.utils.aoa_to_sheet(rows);

            ws['!cols'] = [
                { wch: 6 },
                { wch: 16 },
                { wch: 32 },
                { wch: 18 }
            ];

            XLSX.utils.book_append_sheet(wb, ws, 'Danh sách đã gọi');

            const now = new Date();
            const dateStr = now.toLocaleDateString('vi-VN').replace(/\//g, '-');
            const timeStr = now.toLocaleTimeString('vi-VN').replace(/:/g, '-');
            const fileName = `DanhSach_GoiTen_${dateStr}_${timeStr}.xlsx`;

            XLSX.writeFile(wb, fileName);
            this.showToast(`✅ Đã xuất ${this.selectedStudents.length} sinh viên ra file Excel!`);
        } catch (e) {
            console.error('Export error:', e);
            this.showToast('⚠️ Lỗi khi xuất Excel!', 'error');
        }
    }
}

// Global exposure
window.RandomPicker = RandomPicker;

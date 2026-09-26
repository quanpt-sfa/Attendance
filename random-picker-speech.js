(function (root, factory) {
    const api = factory(root);
    if (typeof module === 'object' && module.exports) {
        module.exports = api;
    } else {
        root.RandomPickerSpeech = api;
        if (typeof RandomPicker !== 'undefined') {
            api.installRandomPicker(RandomPicker);
        }
    }
})(typeof globalThis !== 'undefined' ? globalThis : this, function (root) {
    let currentAudio = null;
    let currentCleanup = null;

    function makeFallback(fn) {
        let used = false;
        return async function fallbackOnce() {
            if (used) return 'fallback';
            used = true;
            if (typeof fn === 'function') {
                await fn();
            }
            return 'fallback';
        };
    }

    async function resolveClassId(student, fetchImpl) {
        const existing = student && (student.classId || student.class_id);
        if (existing) return existing;

        const response = await fetchImpl('/api/sessions/current');
        if (!response || !response.ok) {
            throw new Error('No current attendance session');
        }
        const session = await response.json();
        const classId = session && session.class_id;
        if (!classId) {
            throw new Error('Current attendance session has no class');
        }
        student.classId = classId;
        return classId;
    }

    function stopCurrentAudio() {
        if (currentAudio && typeof currentAudio.pause === 'function') {
            try { currentAudio.pause(); } catch (_) { /* best effort */ }
        }
        if (typeof currentCleanup === 'function') {
            currentCleanup();
        }
        currentAudio = null;
        currentCleanup = null;
    }

    async function playStudentName(student, options = {}) {
        if (options.soundEnabled === false) return 'silent';

        const fallback = makeFallback(options.fallback);
        if (!student || student.ttsDatabaseSource === false || !student.maSV) {
            return fallback();
        }

        const fetchImpl = options.fetchImpl || (
            root && typeof root.fetch === 'function' ? root.fetch.bind(root) : null
        );
        if (!fetchImpl) return fallback();

        try {
            const classId = await resolveClassId(student, fetchImpl);
            const url = `/api/tts/student/${encodeURIComponent(student.maSV)}?class_id=${encodeURIComponent(classId)}`;
            const response = await fetchImpl(url);
            if (!response || !response.ok || typeof response.blob !== 'function') {
                return fallback();
            }

            const blob = await response.blob();
            const AudioCtor = options.AudioCtor || (root && root.Audio);
            const createObjectURL = options.createObjectURL || (
                root && root.URL && typeof root.URL.createObjectURL === 'function'
                    ? root.URL.createObjectURL.bind(root.URL)
                    : null
            );
            const revokeObjectURL = options.revokeObjectURL || (
                root && root.URL && typeof root.URL.revokeObjectURL === 'function'
                    ? root.URL.revokeObjectURL.bind(root.URL)
                    : null
            );

            if (!AudioCtor || !createObjectURL) return fallback();

            stopCurrentAudio();
            const objectUrl = createObjectURL(blob);
            const audio = new AudioCtor(objectUrl);
            let cleaned = false;
            const cleanup = () => {
                if (cleaned) return;
                cleaned = true;
                if (revokeObjectURL) {
                    try { revokeObjectURL(objectUrl); } catch (_) { /* best effort */ }
                }
                if (currentAudio === audio) {
                    currentAudio = null;
                    currentCleanup = null;
                }
            };

            audio.onended = cleanup;
            audio.onerror = cleanup;
            currentAudio = audio;
            currentCleanup = cleanup;

            try {
                await Promise.resolve(audio.play());
            } catch (_) {
                cleanup();
                return fallback();
            }
            return 'local';
        } catch (_) {
            return fallback();
        }
    }

    function installRandomPicker(RandomPickerCtor) {
        if (!RandomPickerCtor || !RandomPickerCtor.prototype) return false;
        const proto = RandomPickerCtor.prototype;
        if (proto.__attendanceLocalTTSInstalled) return true;

        const originalSetStudents = proto.setStudents;
        const originalSpeakName = proto.speakName;
        if (typeof originalSetStudents !== 'function' || typeof originalSpeakName !== 'function') {
            return false;
        }

        proto.setStudents = function (studentList) {
            const source = Array.isArray(studentList) ? studentList : [];
            const result = originalSetStudents.call(this, studentList);
            const isExcelSource = this.activeSource === 'excel' || source === this.excelStudents;
            const databaseSource = !isExcelSource;
            (this.students || []).forEach((student, index) => {
                const raw = source[index] || {};
                student.classId = raw.classId || raw.class_id || student.classId || '';
                student.ttsDatabaseSource = databaseSource;
            });
            return result;
        };

        proto.speakName = function (name) {
            if (!this.soundEnabled) return;
            const student = (this.students || []).find(item => item && item.fullName === name);
            if (!student || !student.ttsDatabaseSource || !student.maSV) {
                return originalSpeakName.call(this, name);
            }

            return playStudentName(student, {
                soundEnabled: this.soundEnabled,
                fallback: () => originalSpeakName.call(this, name),
            });
        };

        proto.__attendanceLocalTTSInstalled = true;
        return true;
    }

    return {
        playStudentName,
        installRandomPicker,
        stopCurrentAudio,
    };
});

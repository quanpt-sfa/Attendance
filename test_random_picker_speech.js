'use strict';

const assert = require('assert');
const Speech = require('./random-picker-speech.js');

async function testLocalAudioSuppressesFallback() {
  const calls = [];
  let fallback = 0;
  let revoked = 0;

  class FakeAudio {
    constructor(url) { this.url = url; calls.push(['audio', url]); }
    play() { calls.push(['play']); return Promise.resolve(); }
  }

  const result = await Speech.playStudentName(
    { maSV: 'SV 01', fullName: 'Nguyễn Văn An', classId: 'L 01', ttsDatabaseSource: true },
    {
      soundEnabled: true,
      fetchImpl: async (url) => {
        calls.push(['fetch', url]);
        return { ok: true, blob: async () => ({ fake: true }) };
      },
      AudioCtor: FakeAudio,
      createObjectURL: () => 'blob:local',
      revokeObjectURL: () => { revoked += 1; },
      fallback: () => { fallback += 1; },
    }
  );

  assert.strictEqual(result, 'local');
  assert.strictEqual(fallback, 0);
  assert.ok(calls.some(x => x[0] === 'fetch' && x[1] === '/api/tts/student/SV%2001?class_id=L%2001'));
  assert.strictEqual(revoked, 0, 'object URL should remain until playback ends');
}

async function testFailureFallsBackExactlyOnce() {
  let fallback = 0;
  const result = await Speech.playStudentName(
    { maSV: 'SV01', fullName: 'Nguyễn Văn An', classId: 'L01', ttsDatabaseSource: true },
    {
      fetchImpl: async () => ({ ok: false, status: 503 }),
      fallback: () => { fallback += 1; },
    }
  );
  assert.strictEqual(result, 'fallback');
  assert.strictEqual(fallback, 1);
}

async function testMissingClassResolvesCurrentSessionThenCachesClass() {
  const urls = [];
  const student = { maSV: 'SV01', fullName: 'Nguyễn Văn An', ttsDatabaseSource: true };
  class FakeAudio { play() { return Promise.resolve(); } }

  const result = await Speech.playStudentName(student, {
    fetchImpl: async (url) => {
      urls.push(url);
      if (url === '/api/sessions/current') {
        return { ok: true, json: async () => ({ class_id: 'C1' }) };
      }
      return { ok: true, blob: async () => ({}) };
    },
    AudioCtor: FakeAudio,
    createObjectURL: () => 'blob:x',
    revokeObjectURL: () => {},
    fallback: () => { throw new Error('fallback should not run'); },
  });

  assert.strictEqual(result, 'local');
  assert.strictEqual(student.classId, 'C1');
  assert.deepStrictEqual(urls, [
    '/api/sessions/current',
    '/api/tts/student/SV01?class_id=C1',
  ]);
}

async function testExcelSourceSkipsNetworkAndUsesFallback() {
  let fetches = 0;
  let fallback = 0;
  const result = await Speech.playStudentName(
    { maSV: 'SV01', fullName: 'Nguyễn Văn An', ttsDatabaseSource: false },
    {
      fetchImpl: async () => { fetches += 1; throw new Error('should not fetch'); },
      fallback: () => { fallback += 1; },
    }
  );
  assert.strictEqual(result, 'fallback');
  assert.strictEqual(fetches, 0);
  assert.strictEqual(fallback, 1);
}

async function testSoundDisabledIsSilent() {
  let fetches = 0;
  let fallback = 0;
  const result = await Speech.playStudentName(
    { maSV: 'SV01', classId: 'C1', ttsDatabaseSource: true },
    {
      soundEnabled: false,
      fetchImpl: async () => { fetches += 1; },
      fallback: () => { fallback += 1; },
    }
  );
  assert.strictEqual(result, 'silent');
  assert.strictEqual(fetches, 0);
  assert.strictEqual(fallback, 0);
}

function makePickerClass() {
  function Picker() {
    this.students = [];
    this.excelStudents = [];
    this.activeSource = 'checkedin';
    this.soundEnabled = true;
  }
  Picker.prototype.setStudents = function (list) {
    this.students = list.map(s => ({ maSV: s.maSV || '', fullName: s.fullName || '' }));
  };
  Picker.prototype.speakName = function (name) { this.browserSpoken = name; };
  Speech.installRandomPicker(Picker);
  return Picker;
}

function testInstallPatchPreservesClassAndDatabaseSource() {
  const Picker = makePickerClass();
  const picker = new Picker();
  picker.setStudents([{ maSV: 'S1', fullName: 'Tên Một', class_id: 'C1' }]);
  assert.strictEqual(picker.students[0].classId, 'C1');
  assert.strictEqual(picker.students[0].ttsDatabaseSource, true);

  picker.activeSource = 'excel';
  picker.setStudents([{ maSV: 'S2', fullName: 'Tên Hai' }]);
  assert.strictEqual(picker.students[0].ttsDatabaseSource, false);
}

function testStandaloneDirectExcelUploadIsNotMarkedAsDatabaseSource() {
  const Picker = makePickerClass();
  const picker = new Picker();
  const parsedExcel = [{ maSV: 'X1', fullName: 'Tên Excel' }];
  picker.excelStudents = parsedExcel;
  assert.strictEqual(picker.activeSource, 'checkedin', 'standalone upload leaves default source unchanged');
  picker.setStudents(parsedExcel);
  assert.strictEqual(picker.students[0].ttsDatabaseSource, false);
}

(async () => {
  await testLocalAudioSuppressesFallback();
  await testFailureFallsBackExactlyOnce();
  await testMissingClassResolvesCurrentSessionThenCachesClass();
  await testExcelSourceSkipsNetworkAndUsesFallback();
  await testSoundDisabledIsSilent();
  testInstallPatchPreservesClassAndDatabaseSource();
  testStandaloneDirectExcelUploadIsNotMarkedAsDatabaseSource();
  console.log('PASS random-picker local speech tests');
})().catch(err => {
  console.error(err);
  process.exit(1);
});

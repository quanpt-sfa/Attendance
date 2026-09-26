const assert = require('assert');
const {
  findOpenSession,
  checkedInStudents,
  loadPresentStudents,
} = require('./random-picker-attendance.js');

(async () => {
  assert.strictEqual(findOpenSession([{session_id: 1, is_open: 0}, {session_id: 2, is_open: 1}]).session_id, 2);
  assert.strictEqual(findOpenSession([{session_id: 1, is_open: 0}]), null);

  const filtered = checkedInStudents([
    {student_id: 'A', check_type: 'in', name: 'Nguyen A', photo_path: 'a.jpg'},
    {student_id: 'B', check_type: 'out', name: 'Tran B'},
    {student_id: 'C', check_type: 'in', name: 'Le C'},
  ]);
  assert.deepStrictEqual(filtered.map(s => s.maSV), ['A', 'C']);
  assert.strictEqual(filtered[0].photoUrl, '/photos/a.jpg');

  const noSessionCalls = [];
  const noSession = await loadPresentStudents('L01', async (url) => {
    noSessionCalls.push(url);
    return { ok: true, json: async () => [{session_id: 1, is_open: 0}] };
  });
  assert.strictEqual(noSession.status, 'no-open-session');
  assert.deepStrictEqual(noSession.students, []);
  assert.strictEqual(noSessionCalls.length, 1, 'must not fetch checkins without an open session');

  const calls = [];
  const responses = [
    [{session_id: 10, is_open: 1}],
    [
      {student_id: 'A', check_type: 'in', name: 'Nguyen A'},
      {student_id: 'B', check_type: 'out', name: 'Tran B'},
    ],
  ];
  const result = await loadPresentStudents('L 01', async (url) => {
    calls.push(url);
    return { ok: true, json: async () => responses.shift() };
  });
  assert.strictEqual(result.status, 'ok');
  assert.deepStrictEqual(result.students.map(s => s.maSV), ['A']);
  assert.ok(calls[0].includes('class_id=L%2001'));
  assert.ok(calls[1].includes('session_id=10'));

  console.log('PASS random-picker attendance-only tests');
})().catch(err => {
  console.error(err);
  process.exit(1);
});

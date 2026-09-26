(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) {
    module.exports = api;
  } else {
    root.RandomPickerAttendance = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  function findOpenSession(sessions) {
    if (!Array.isArray(sessions)) return null;
    return sessions.find(session => Number(session.is_open) === 1) || null;
  }

  function checkedInStudents(checkins) {
    if (!Array.isArray(checkins)) return [];
    const seen = new Set();
    return checkins
      .filter(checkin => checkin && checkin.check_type === 'in' && checkin.student_id)
      .filter(checkin => {
        if (seen.has(checkin.student_id)) return false;
        seen.add(checkin.student_id);
        return true;
      })
      .map(checkin => ({
        maSV: checkin.student_id,
        ho: checkin.last_name || '',
        ten: checkin.first_name || '',
        fullName: checkin.name || checkin.full_name || checkin.student_id,
        photoUrl: checkin.photo_path ? `/photos/${checkin.photo_path}` : '',
      }));
  }

  async function fetchJson(url, fetchImpl) {
    const response = await fetchImpl(url);
    if (!response || response.ok === false) {
      throw new Error(`Request failed: ${url}`);
    }
    return response.json();
  }

  async function loadPresentStudents(classId, fetchImpl) {
    const doFetch = fetchImpl || (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null);
    if (!doFetch) throw new Error('fetch is not available');

    const sessions = await fetchJson(
      `/api/sessions?class_id=${encodeURIComponent(classId)}`,
      doFetch
    );
    const session = findOpenSession(sessions);
    if (!session) {
      return { status: 'no-open-session', session: null, students: [] };
    }

    const checkins = await fetchJson(
      `/api/checkins?session_id=${encodeURIComponent(session.session_id)}`,
      doFetch
    );
    const students = checkedInStudents(checkins);
    return {
      status: students.length > 0 ? 'ok' : 'no-checked-in-students',
      session,
      students,
    };
  }

  return {
    findOpenSession,
    checkedInStudents,
    loadPresentStudents,
  };
});

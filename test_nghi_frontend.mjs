import assert from 'node:assert/strict';
import { Readable, Writable } from 'node:stream';

import {
  processFrontendRequest,
  serveNdjson,
  toOnnxScalarIds,
} from './tts/nghi_frontend.mjs';

const CASE2 = 'Huỳnh Quốc Phước đã điểm danh thành công. Mời sinh viên tiếp theo.';

function makeFrontend(handler) {
  return { process: handler };
}

async function test_preserves_request_id_and_source_case() {
  const seen = [];
  const frontend = makeFrontend(async (text) => {
    seen.push(text);
    return {
      processed_text: text,
      chunks: [{ text, phoneme_ids: [1, 0, 2] }],
    };
  });
  const response = await processFrontendRequest(frontend, {
    id: 'Req-ABC', action: 'frontend', text: CASE2,
  });
  assert.equal(response.id, 'Req-ABC');
  assert.equal(response.ok, true);
  assert.deepEqual(seen, [CASE2]);
  assert.equal(response.processed_text, CASE2);
}

async function test_case2_returns_two_chunks() {
  const frontend = makeFrontend(async () => ({
    processed_text: 'huỳnh quốc phước đã điểm danh thành công. mời sinh viên tiếp theo.',
    chunks: [
      { text: 'huỳnh quốc phước đã điểm danh thành công.', phoneme_ids: [1, 0, 10, 0, 2] },
      { text: 'mời sinh viên tiếp theo.', phoneme_ids: [1, 0, 10, 0, 2] },
    ],
  }));
  const response = await processFrontendRequest(frontend, {
    id: '2', action: 'frontend', text: CASE2,
  });
  assert.equal(response.ok, true);
  assert.equal(response.chunks.length, 2);
  assert.match(response.chunks[0].text, /thành công\.$/);
  assert.match(response.chunks[1].text, /^mời sinh viên/);
}

async function test_comma_stays_inside_one_chunk() {
  const text = 'Huỳnh Quốc Phước, bạn đã điểm danh thành công.';
  const frontend = makeFrontend(async () => ({
    processed_text: text.toLowerCase(),
    chunks: [{ text: text.toLowerCase(), phoneme_ids: [1, 0, 8, 0, 2] }],
  }));
  const response = await processFrontendRequest(frontend, {
    id: '3', action: 'frontend', text,
  });
  assert.equal(response.chunks.length, 1);
  assert.ok(response.chunks[0].text.includes(','));
}

async function test_question_and_exclamation_follow_nghi_chunking() {
  for (const punctuation of ['!', '?']) {
    const text = `Bạn đã điểm danh thành công${punctuation}`;
    const frontend = makeFrontend(async () => ({
      processed_text: text.toLowerCase(),
      chunks: [{ text: text.toLowerCase(), phoneme_ids: [1, 0, 2] }],
    }));
    const response = await processFrontendRequest(frontend, {
      id: punctuation, action: 'frontend', text,
    });
    assert.equal(response.chunks.length, 1);
    assert.ok(response.chunks[0].text.endsWith(punctuation));
  }
}

function test_phoneme_ids_are_scalar_integers() {
  assert.deepEqual(toOnnxScalarIds([[1], [0], [137], [2]]), [1, 0, 137, 2]);
  assert.throws(() => toOnnxScalarIds([1.5]), /phoneme id/i);
  assert.throws(() => toOnnxScalarIds(['abc']), /phoneme id/i);
}

async function collectOutput(lines, frontend) {
  let stdout = '';
  let stderr = '';
  const input = Readable.from(lines.map((line) => `${line}\n`));
  const out = new Writable({ write(chunk, _enc, cb) { stdout += chunk.toString(); cb(); } });
  const err = new Writable({ write(chunk, _enc, cb) { stderr += chunk.toString(); cb(); } });
  await serveNdjson({ stdin: input, stdout: out, stderr: err, frontend });
  return { stdout, stderr };
}

async function test_malformed_request_returns_json_error_only_on_stdout() {
  const { stdout } = await collectOutput(['not-json'], makeFrontend(async () => { throw new Error('unused'); }));
  const lines = stdout.trim().split(/\r?\n/);
  assert.equal(lines.length, 1);
  const response = JSON.parse(lines[0]);
  assert.equal(response.ok, false);
  assert.equal(response.id, null);
}

async function test_nghi_debug_output_stays_on_stderr() {
  const frontend = makeFrontend(async (text, diagnostics) => {
    diagnostics.write('[NGHI] debug\n');
    return { processed_text: text, chunks: [{ text, phoneme_ids: [1, 0, 2] }] };
  });
  const request = JSON.stringify({ id: 'debug', action: 'frontend', text: 'Xin chào.' });
  const { stdout, stderr } = await collectOutput([request], frontend);
  assert.doesNotThrow(() => JSON.parse(stdout.trim()));
  assert.match(stderr, /\[NGHI\] debug/);
  assert.doesNotMatch(stdout, /\[NGHI\]/);
}

const tests = [
  test_preserves_request_id_and_source_case,
  test_case2_returns_two_chunks,
  test_comma_stays_inside_one_chunk,
  test_question_and_exclamation_follow_nghi_chunking,
  test_phoneme_ids_are_scalar_integers,
  test_malformed_request_returns_json_error_only_on_stdout,
  test_nghi_debug_output_stays_on_stderr,
];

for (const test of tests) {
  await test();
  console.log(`ok - ${test.name}`);
}

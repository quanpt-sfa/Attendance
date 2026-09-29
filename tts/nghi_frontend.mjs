import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import readline from 'node:readline';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

function writeDiagnostic(stream, prefix, values) {
  if (!stream || typeof stream.write !== 'function') return;
  const text = values.map((value) => {
    if (typeof value === 'string') return value;
    try { return JSON.stringify(value); } catch (_) { return String(value); }
  }).join(' ');
  stream.write(`${prefix}${text}\n`);
}

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (!key?.startsWith('--') || value === undefined) {
      throw new Error(`Invalid argument near ${key ?? '<end>'}`);
    }
    args[key.slice(2)] = value;
  }
  return args;
}

export function toOnnxScalarIds(rawIds) {
  if (!Array.isArray(rawIds)) {
    throw new Error('NGHI phoneme ids must be an array');
  }
  return rawIds.map((value) => {
    try {
      const integer = BigInt(value);
      const numeric = Number(integer);
      if (!Number.isSafeInteger(numeric)) throw new Error('outside safe integer range');
      return numeric;
    } catch (error) {
      throw new Error(`Invalid phoneme id ${JSON.stringify(value)}`, { cause: error });
    }
  });
}

function installLocalFetch(nghiRoot) {
  const nativeFetch = globalThis.fetch;
  globalThis.fetch = async (resource, options = {}) => {
    const raw = typeof resource === 'string' ? resource : resource?.url;
    if (typeof raw === 'string' && raw.startsWith('/')) {
      const localPath = path.join(nghiRoot, 'public', raw.slice(1));
      try {
        const bytes = await fs.readFile(localPath);
        return new Response(bytes, { status: 200 });
      } catch (error) {
        if (error?.code === 'ENOENT') {
          return new Response('', { status: 404, statusText: 'Not Found' });
        }
        throw error;
      }
    }
    if (!nativeFetch) {
      throw new Error(`No fetch implementation available for ${raw}`);
    }
    return nativeFetch(resource, options);
  };
}

export async function createNghiFrontend({ nghiRoot, voiceConfigPath, expectedCommit }) {
  const root = path.resolve(nghiRoot);
  const configPath = path.resolve(voiceConfigPath);
  const actualCommit = execFileSync('git', ['-C', root, 'rev-parse', 'HEAD'], {
    encoding: 'utf8',
  }).trim();
  if (actualCommit !== expectedCommit) {
    throw new Error(`NGHI checkout mismatch: expected ${expectedCommit}, got ${actualCommit}`);
  }

  installLocalFetch(root);
  const cleanerUrl = pathToFileURL(path.join(root, 'src', 'utils', 'text-cleaner.js')).href;
  const piperUrl = pathToFileURL(path.join(root, 'src', 'lib', 'piper-tts.js')).href;
  const { processTextForTTS, chunkText } = await import(cleanerUrl);
  const { PiperTTS } = await import(piperUrl);
  const voiceConfig = JSON.parse(await fs.readFile(configPath, 'utf8'));
  const tts = new PiperTTS(voiceConfig, null);

  return {
    async process(text, diagnostics = process.stderr) {
      const originalLog = console.log;
      const originalWarn = console.warn;
      console.log = (...values) => writeDiagnostic(diagnostics, '[NGHI] ', values);
      console.warn = (...values) => writeDiagnostic(diagnostics, '[NGHI warn] ', values);
      try {
        const processedText = await processTextForTTS(text);
        const chunks = await chunkText(processedText);
        const outputChunks = [];
        for (const chunk of chunks || []) {
          if (!String(chunk || '').trim()) continue;
          const phonemeGroups = await tts.textToPhonemes(chunk);
          const rawIds = await tts.phonemesToIds(phonemeGroups);
          outputChunks.push({
            text: chunk,
            phoneme_ids: toOnnxScalarIds(rawIds),
          });
        }
        return { processed_text: processedText, chunks: outputChunks };
      } finally {
        console.log = originalLog;
        console.warn = originalWarn;
      }
    },
  };
}

function validateFrontendResult(result) {
  if (!result || typeof result !== 'object') throw new Error('NGHI frontend returned no result');
  if (!Array.isArray(result.chunks) || result.chunks.length === 0) {
    throw new Error('NGHI frontend returned no chunks');
  }
  const chunks = result.chunks.map((chunk) => {
    if (!chunk || typeof chunk.text !== 'string') throw new Error('NGHI chunk text is invalid');
    if (!Array.isArray(chunk.phoneme_ids) || chunk.phoneme_ids.length === 0) {
      throw new Error('NGHI chunk phoneme ids are empty');
    }
    for (const id of chunk.phoneme_ids) {
      if (!Number.isSafeInteger(id)) throw new Error('NGHI chunk phoneme id is not a scalar integer');
    }
    return { text: chunk.text, phoneme_ids: [...chunk.phoneme_ids] };
  });
  return { processed_text: String(result.processed_text ?? ''), chunks };
}

export async function processFrontendRequest(frontend, request, diagnostics = process.stderr) {
  const requestId = request && typeof request === 'object' ? request.id ?? null : null;
  try {
    if (!request || typeof request !== 'object' || Array.isArray(request)) {
      throw new Error('Request must be a JSON object');
    }
    if (request.action !== 'frontend') throw new Error('Unsupported action');
    if (typeof request.text !== 'string' || !request.text.trim()) {
      throw new Error('Frontend text is empty');
    }
    const result = validateFrontendResult(await frontend.process(request.text, diagnostics));
    return { id: requestId, ok: true, ...result };
  } catch (error) {
    return { id: requestId, ok: false, error: String(error?.message || error) };
  }
}

export async function serveNdjson({ stdin, stdout, stderr, frontend }) {
  const lines = readline.createInterface({ input: stdin, crlfDelay: Infinity });
  for await (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;
    let request;
    let response;
    try {
      request = JSON.parse(line);
    } catch (error) {
      writeDiagnostic(stderr, 'Invalid JSON request: ', [error.message]);
      response = { id: null, ok: false, error: 'Invalid JSON request' };
    }
    if (!response) {
      response = await processFrontendRequest(frontend, request, stderr);
      if (!response.ok) writeDiagnostic(stderr, 'NGHI frontend request failed: ', [response.error]);
    }
    stdout.write(`${JSON.stringify(response)}\n`);
  }
}

async function runCli() {
  const args = parseArgs(process.argv.slice(2));
  if (!args['nghi-root'] || !args['voice-config'] || !args['expected-commit']) {
    throw new Error('--nghi-root, --voice-config and --expected-commit are required');
  }
  console.log = (...values) => writeDiagnostic(process.stderr, '[NGHI] ', values);
  console.warn = (...values) => writeDiagnostic(process.stderr, '[NGHI warn] ', values);
  const frontend = await createNghiFrontend({
    nghiRoot: args['nghi-root'],
    voiceConfigPath: args['voice-config'],
    expectedCommit: args['expected-commit'],
  });
  await serveNdjson({ stdin: process.stdin, stdout: process.stdout, stderr: process.stderr, frontend });
}

const invokedPath = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : '';
if (import.meta.url === invokedPath) {
  runCli().catch((error) => {
    writeDiagnostic(process.stderr, 'NGHI frontend fatal: ', [error?.stack || error]);
    process.exitCode = 1;
  });
}

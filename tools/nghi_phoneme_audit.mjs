import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

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

function toOnnxScalarIds(rawIds) {
  return rawIds.map((value) => {
    // NGHI's phonemesToIds pushes idMap entries such as [10]. Immediately before
    // ONNX it executes BigInt(id), so [10] is coerced to 10n. Reproduce that exact
    // coercion here and report the scalar tensor sequence, not nested config arrays.
    try {
      return Number(BigInt(value));
    } catch (error) {
      throw new Error(`Cannot coerce NGHI phoneme id ${JSON.stringify(value)} to ONNX int64`, {
        cause: error,
      });
    }
  });
}

const args = parseArgs(process.argv.slice(2));
const nghiRoot = path.resolve(args['nghi-root'] || '');
const voiceConfigPath = path.resolve(args['voice-config'] || '');
const expectedCommit = args['expected-commit'];
if (!nghiRoot || !voiceConfigPath || !expectedCommit) {
  throw new Error('--nghi-root, --voice-config and --expected-commit are required');
}

const actualCommit = execFileSync('git', ['-C', nghiRoot, 'rev-parse', 'HEAD'], {
  encoding: 'utf8',
}).trim();
if (actualCommit !== expectedCommit) {
  throw new Error(`NGHI checkout mismatch: expected ${expectedCommit}, got ${actualCommit}`);
}

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

// NGHI-TTS has debug=true in its pinned config and writes preprocessing details to
// console.log. Redirect those diagnostics to stderr so stdout remains one JSON object.
console.log = (...values) => console.error('[NGHI]', ...values);
console.warn = (...values) => console.error('[NGHI warn]', ...values);

const cleanerUrl = pathToFileURL(path.join(nghiRoot, 'src', 'utils', 'text-cleaner.js')).href;
const piperUrl = pathToFileURL(path.join(nghiRoot, 'src', 'lib', 'piper-tts.js')).href;
const { processTextForTTS, chunkText } = await import(cleanerUrl);
const { PiperTTS } = await import(piperUrl);
const voiceConfig = JSON.parse(await fs.readFile(voiceConfigPath, 'utf8'));
const tts = new PiperTTS(voiceConfig, null);

let stdin = '';
for await (const chunk of process.stdin) {
  stdin += chunk;
}
const request = JSON.parse(stdin || '{}');
if (!Array.isArray(request.sentences)) {
  throw new Error('stdin JSON must contain a sentences array');
}

const cases = [];
for (const original of request.sentences) {
  const processedText = await processTextForTTS(original);
  const chunks = await chunkText(processedText);
  const auditedChunks = [];

  for (const text of chunks) {
    const phonemeGroups = await tts.textToPhonemes(text);
    const rawPhonemeIds = await tts.phonemesToIds(phonemeGroups);
    const phonemeIds = toOnnxScalarIds(rawPhonemeIds);
    auditedChunks.push({
      text,
      phoneme_groups: phonemeGroups.map((group) => group.join('')),
      phoneme_string: phonemeGroups.map((group) => group.join('')).join(' | '),
      phoneme_ids: phonemeIds,
    });
  }

  cases.push({
    original,
    processed_text: processedText,
    chunks: auditedChunks,
  });
}

process.stdout.write(JSON.stringify({
  metadata: {
    nghi_commit: actualCommit,
    phonemizer_package: 'phonemizer-1.2.2.tgz',
  },
  cases,
}));

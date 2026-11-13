import { readFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { generateRoadmap, validateInput, validateResult } from './gemini/roadmap.mjs';

// 공급자 선택: AI_PROVIDER=gemini 또는 AI_PROVIDER=local (기본값 gemini).
const provider = process.env.AI_PROVIDER || 'gemini';
try {
  const input = JSON.parse(await readFile(process.argv[2], 'utf8'));
  validateInput(input);
  let result;
  if (provider === 'gemini') result = await generateRoadmap(input);
  else if (provider === 'local') {
    const child = spawnSync(process.env.AI_PYTHON || 'python', ['ai/local/infer.py'], { input: JSON.stringify(input), encoding: 'utf8', env: { ...process.env, PYTHONUTF8: '1' }, maxBuffer: 8 * 1024 * 1024, timeout: 180000 });
    if (child.error || child.status !== 0) throw new Error('로컬 모델 실행 실패: ' + (child.stderr || child.error?.message || '설정을 확인하세요'));
    result = validateResult(JSON.parse(child.stdout), input);
  } else throw new Error('AI_PROVIDER는 gemini 또는 local이어야 합니다.');
  const output = JSON.stringify(result, null, 2);
  const key = process.env.GEMINI_API_KEY;
  console.log(key ? output.split(key).join('[API_KEY 숨김]') : output);
} catch (error) {
  const key = process.env.GEMINI_API_KEY;
  const message = String(error.message);
  console.error(key ? message.split(key).join('[API_KEY 숨김]') : message);
  process.exitCode = 1;
}

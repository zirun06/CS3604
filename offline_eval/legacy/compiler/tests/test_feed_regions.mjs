import assert from 'node:assert/strict';
import { mkdtempSync, readFileSync, writeFileSync, unlinkSync, rmdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { resolve } from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const workspace = resolve(process.argv[2]);
const ts = createRequire(resolve(workspace, 'package.json'))('typescript');
const script = fileURLToPath(new URL('../infrastructure/tasks/associate_status_labels.mjs', import.meta.url));
const temporary = mkdtempSync(resolve(tmpdir(), 'arc-feed-region-'));
const path = resolve(temporary, 'fixture.tsx');
function run(text) {
  writeFileSync(path, text);
  const result = spawnSync(process.execPath, [script, workspace, path], { encoding:'utf8' });
  assert.equal(result.status, 0, result.stderr);
  return {text:readFileSync(path,'utf8'),...JSON.parse(result.stdout)};
}
try {
  const original = `const Feed = () => <div className="feed"><div><button onClick={ask}>Ask Question</button></div>
    <div role="region" aria-label="Question feed" className="list">{rows}</div>
    <button onClick={next}>Next page</button></div>;`;
  const result = run(original);
  assert.equal(result.associated_feed_regions, 1);
  assert.equal((result.text.match(/aria-label="Question feed"/g)||[]).length, 1);
  const ast = ts.createSourceFile(path,result.text,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
  assert.equal(ast.parseDiagnostics.length,0);
  assert.match(result.text,/className="feed" role="region" aria-label="Question feed"/);
  assert.ok(result.text.includes('<button onClick={ask}>Ask Question</button>'));
  assert.ok(result.text.includes('<button onClick={next}>Next page</button>'));
  assert.equal(run(result.text).text,result.text,'A second pass must be idempotent');
  for (const text of [
    '<main><button>Ask Question</button><div role="region" aria-label="Question feed">{rows}</div></main>',
    '<div role="region" aria-label="Existing"><button>Ask Question</button><div role="region" aria-label="Question feed">{rows}</div></div>',
    '<div><nav>Home</nav><button>Ask Question</button><div role="region" aria-label="Question feed">{rows}</div></div>',
    '<div><button>Ask Question</button><div role="region" aria-label="Question feed">{rows}</div><div role="region" aria-label="Question feed">{other}</div></div>',
    '<div {...props}><button>Ask Question</button><div role="region" aria-label="Question feed">{rows}</div></div>',
    '<div><button>Ask Question</button><div role="region" aria-label="Question feed" {...props}>{rows}</div></div>',
  ]) assert.equal(run('const Feed = () => '+text+';').associated_feed_regions,0);
  console.log('Feed region checks passed: scope, handlers, layout nodes, syntax, idempotence, protected/ambiguous landmarks.');
} finally { unlinkSync(path); rmdirSync(temporary); }

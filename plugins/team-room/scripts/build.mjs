// @meijamke/dsh-team-room — client 打包脚本(零依赖:npm run build:client)
//
// 产物 client.bundle.js 是 client-modules 期望的格式:
//   window.__ModuleLoader__.load({ id, factory: (require) => { ...CJS... } })
// 打包器:esbuild(优先读环境变量 ESBUILD_BIN,否则在常见位置查找)。
// 产物直接提交进仓库,普通使用者无需执行本脚本。

import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const PLUGIN_ID = '@meijamke/dsh-team-room'

const candidates = [
  process.env.ESBUILD_BIN,
  '/home/weiyuanxin/deepseek_harness/deepseek-harness/node_modules/.bin/esbuild',
  join(root, 'node_modules/.bin/esbuild'),
  'esbuild',
].filter(Boolean)

/** 依次挑选一个能正常工作的 esbuild。 */
function pickEsbuild() {
  for (const candidate of candidates) {
    const probe = spawnSync(candidate, ['--version'], { encoding: 'utf8' })
    if (probe.status === 0) {
      process.stderr.write(`using esbuild: ${candidate} (${String(probe.stdout).trim()})\n`)
      return candidate
    }
  }
  return null
}

const esbuild = pickEsbuild()
if (esbuild === null) {
  process.stderr.write('esbuild not found; set ESBUILD_BIN to an esbuild binary\n')
  process.exit(1)
}

const intermediate = join(root, '.client.intermediate.cjs')
const args = [
  join(root, 'client.src.js'),
  '--bundle',
  '--format=cjs',
  '--platform=browser',
  '--external:react',
  '--outfile=' + intermediate,
  '--log-level=error',
]

const run = spawnSync(esbuild, args, { stdio: 'inherit' })
if (run.status !== 0) {
  process.stderr.write(`esbuild failed (${esbuild})\n`)
  process.exit(run.status ?? 1)
}

const core = readFileSync(intermediate, 'utf8')
const wrapper = `window.__ModuleLoader__.load({
\tid: ${JSON.stringify(PLUGIN_ID)},
\tfactory: (require) => {
\t\tvar module = { exports: {} };
\t\tvar exports = module.exports;
${core}
\t\treturn module.exports;
\t}
});
`
writeFileSync(join(root, 'client.bundle.js'), wrapper)
process.stdout.write(`built client.bundle.js (${wrapper.length} bytes)\n`)

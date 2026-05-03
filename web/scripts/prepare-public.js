import { execFileSync } from 'child_process'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const root = resolve(__dirname, '../..')

try {
  execFileSync('python', ['-m', 'media_advisor.tools.dump_analysis_public'], {
    cwd: root,
    stdio: 'inherit',
    shell: false,
  })
} catch (e) {
  // eslint-disable-next-line no-console
  console.warn(
    '[prepare-public] Python dump failed (is the package installed? pip install -e .).',
    e?.message ?? e
  )
}

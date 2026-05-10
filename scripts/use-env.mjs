/**
 * Switching script per la configurazione multi-livello .env.
 * Tutti i file env risiedono nella cartella environment/.
 *
 * Usage:
 *   node scripts/use-env.mjs <provider> <environment>
 *   node scripts/use-env.mjs --status
 *
 * Esempi:
 *   node scripts/use-env.mjs deepinfra prod   → environment/.env.deepinfra + environment/.env.prod → environment/.env.local
 *   node scripts/use-env.mjs openai test       → environment/.env.openai + environment/.env.test → environment/.env.local
 *   node scripts/use-env.mjs --status          → mostra config attiva
 *
 * Provider supportati: deepinfra, groq, openai
 * Environment supportati: test, prod
 */

import { readFileSync, writeFileSync, existsSync } from 'fs'
import { join } from 'path'

const ENV_DIR = 'environment'
const args = process.argv.slice(2)

function envPath(name) {
  return join(ENV_DIR, name)
}

if (args[0] === '--status') {
  const localFile = envPath('.env.local')
  if (!existsSync(localFile)) {
    console.log('Nessuna config attiva (environment/.env.local assente).')
    console.log('Esegui: npm run env:<provider>:<environment>')
    console.log('  es: npm run env:deepinfra:prod')
  } else {
    const first = readFileSync(localFile, 'utf8').split('\n')[0]
    console.log(first.startsWith('#') ? first : 'environment/.env.local esiste (header non riconosciuto)')
  }
  process.exit(0)
}

const [provider, environment] = args

if (!provider || !environment) {
  console.error('Errore: provider e environment richiesti.')
  console.error('Usage:  node scripts/use-env.mjs <provider> <environment>')
  console.error('        node scripts/use-env.mjs --status')
  console.error('')
  console.error('Esempi: npm run env:deepinfra:prod')
  console.error('        npm run env:openai:test')
  process.exit(1)
}

const providerFile = envPath(`.env.${provider}`)
const envFile = envPath(`.env.${environment}`)
const outputFile = envPath('.env.local')

const header = `# Active: provider=${provider} environment=${environment} — DO NOT EDIT (generato da use-env.mjs)`
const parts = [header]

if (existsSync(providerFile)) {
  parts.push(readFileSync(providerFile, 'utf8').trim())
} else {
  console.warn(`⚠  ${providerFile} non trovato — crealo da ${providerFile}.example`)
}

if (existsSync(envFile)) {
  parts.push(readFileSync(envFile, 'utf8').trim())
} else {
  console.warn(`⚠  ${envFile} non trovato — crealo da ${envFile}.example`)
}

writeFileSync(outputFile, parts.join('\n\n') + '\n')
console.log(`✓  environment/.env.local aggiornato: provider=${provider} environment=${environment}`)
console.log('   uvicorn --reload rileva il cambio e riavvia il server automaticamente.')

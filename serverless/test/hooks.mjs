const MOCK = new URL('./sdk-mock.mjs', import.meta.url).href
const SECRETS = new URL('./secrets.test.mjs', import.meta.url).href

export async function resolve(specifier, context, next) {
  if (specifier === 'sdk' || specifier.startsWith('sdk/')) return { url: MOCK, shortCircuit: true }
  if (specifier.endsWith('/secrets.js') || specifier === './secrets.js') return { url: SECRETS, shortCircuit: true }
  return next(specifier, context)
}

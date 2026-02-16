import { computed } from 'vue'
import { getMacroList } from '../config/macroTrends.js'

/**
 * @param {import('vue').Ref} enrichedClaimsRef - ref a array di claim arricchiti
 */
export function useMacroTrends(enrichedClaimsRef) {
  const macroList = computed(() => {
    const claims = enrichedClaimsRef?.value ?? enrichedClaimsRef ?? []
    return getMacroList(claims)
  })

  return { macroList }
}

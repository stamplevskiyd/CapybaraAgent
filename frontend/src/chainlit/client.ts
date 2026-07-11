import { ChainlitAPI } from '@chainlit/react-client'

export const CHAINLIT_PATH = '/chainlit'

export function createChainlitClient(path = CHAINLIT_PATH): ChainlitAPI {
  // ChainlitAPI builds absolute URLs internally (new URL(...)), so a bare relative path
  // breaks URL parsing; anchor the mount path to the current origin.
  const endpoint =
    typeof window === 'undefined' ? path : new URL(path, window.location.origin).toString()
  return new ChainlitAPI(endpoint, 'webapp')
}

export const chainlitClient = createChainlitClient()

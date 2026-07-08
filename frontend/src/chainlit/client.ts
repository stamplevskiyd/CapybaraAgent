import { ChainlitAPI } from '@chainlit/react-client'

export const CHAINLIT_HTTP_ENDPOINT = '/chainlit'

export function createChainlitClient(endpoint = CHAINLIT_HTTP_ENDPOINT): ChainlitAPI {
  return new ChainlitAPI(endpoint, 'webapp')
}

export const chainlitClient = createChainlitClient()

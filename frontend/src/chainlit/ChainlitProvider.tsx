import type { ReactNode } from 'react'
import { ChainlitContext } from '@chainlit/react-client'
import { RecoilRoot } from 'recoil'
import { chainlitClient } from './client'

type CapybaraChainlitProviderProps = {
  children: ReactNode
}

export function CapybaraChainlitProvider({ children }: CapybaraChainlitProviderProps) {
  return (
    <ChainlitContext.Provider value={chainlitClient}>
      <RecoilRoot>{children}</RecoilRoot>
    </ChainlitContext.Provider>
  )
}

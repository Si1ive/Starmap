import { create } from 'zustand'

interface AppState {
  // 当前查看的人物
  currentPerson: { id: string; name: string } | null
  setCurrentPerson: (person: { id: string; name: string } | null) => void
  
  // 搜索历史
  searchHistory: string[]
  addSearchHistory: (query: string) => void
  clearSearchHistory: () => void
  
  // 会话ID
  sessionId: string | null
  setSessionId: (id: string | null) => void
}

export const useAppStore = create<AppState>((set) => ({
  currentPerson: null,
  setCurrentPerson: (person) => set({ currentPerson: person }),
  
  searchHistory: [],
  addSearchHistory: (query) =>
    set((state) => ({
      searchHistory: [...new Set([...state.searchHistory, query])].slice(-10)
    })),
  clearSearchHistory: () => set({ searchHistory: [] }),
  
  sessionId: null,
  setSessionId: (id) => set({ sessionId: id })
}))
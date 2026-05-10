/**
 * Vitest 测试环境设置文件
 * 
 * 配置测试所需的全局设置和模拟
 */

import '@testing-library/jest-dom'
import { afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'

// 每个测试后清理
afterEach(() => {
  cleanup()
})

// Mock matchMedia（某些组件需要）
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))

// Mock IntersectionObserver
global.IntersectionObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))

// Mock scrollTo
window.scrollTo = vi.fn()

// Mock fetch (可以在具体测试中覆盖)
global.fetch = vi.fn()

// Some runners inject a partial localStorage object without the Web Storage API methods.
// Normalize it here so tests can rely on the standard interface.
if (!window.localStorage || typeof window.localStorage.setItem !== 'function') {
  let storage = new Map<string, string>()
  const mockStorage = {
    getItem: vi.fn((key: string) => storage.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      storage.set(key, String(value))
    }),
    removeItem: vi.fn((key: string) => {
      storage.delete(key)
    }),
    clear: vi.fn(() => {
      storage = new Map<string, string>()
    }),
    key: vi.fn((index: number) => Array.from(storage.keys())[index] ?? null),
    get length() {
      return storage.size
    },
  }
  Object.defineProperty(window, 'localStorage', {
    value: mockStorage,
    configurable: true,
  })
  Object.defineProperty(globalThis, 'localStorage', {
    value: mockStorage,
    configurable: true,
  })
}

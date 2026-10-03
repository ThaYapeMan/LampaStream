import '@testing-library/jest-dom'

// Radix UI's Slider uses ResizeObserver internally; jsdom doesn't have it.
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}

// Browser appearance APIs are not implemented by jsdom.
window.matchMedia = () => ({ matches: false, media: '', onchange: null,
  addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {},
  dispatchEvent: () => true })

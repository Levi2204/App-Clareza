import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';
HTMLDialogElement.prototype.showModal = function () {
  this.open = true;
};
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

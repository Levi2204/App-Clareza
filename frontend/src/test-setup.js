import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';
HTMLDialogElement.prototype.showModal = function () {
  this.open = true;
};
HTMLDialogElement.prototype.close = function () {
  this.open = false;
};
global.ResizeObserver = class {
  observe() {}
  unobserve() {}
  disconnect() {}
};

// Чистые правила «живости» окна: их можно проверить без DOM.
// Сервер шлёт пульс каждую секунду, окно считает, не завис ли он.

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.OmegaLiveness = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function isStalled(now, lastSignal, running, thresholdSeconds) {
    if (!running) {
      return false;
    }
    const threshold = Math.max(0, Number(thresholdSeconds) || 0) * 1000;
    const last = Number(lastSignal) || 0;
    if (!last) {
      return false;
    }
    return Number(now) - last > threshold;
  }

  function formatElapsed(seconds) {
    const total = Math.max(0, Math.floor(Number(seconds) || 0));
    if (total < 60) {
      return `${total} с`;
    }
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return `${minutes} м ${rest} с`;
  }

  function shouldNotify(options) {
    const data = options && typeof options === "object" ? options : {};
    if (data.windowHidden) {
      return true;
    }
    return Number(data.taskSeconds || 0) >= Number(data.minSeconds || 25);
  }

  return { isStalled, formatElapsed, shouldNotify };
});

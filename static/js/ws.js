// Conexão WebSocket com reconexão automática (1s -> 2s -> 4s ... teto 15s) e ping a cada 20s.
// connect(onEvent, onStatus?) devolve { close() }. Cada mensagem do servidor é um evento JSON.

const PING_MS = 20000;
const BACKOFF_MIN = 1000;
const BACKOFF_MAX = 15000;

export function connect(onEvent, onStatus = () => {}, url = defaultUrl()) {
  let ws = null;
  let backoff = BACKOFF_MIN;
  let pingTimer = null;
  let reconnectTimer = null;
  let closedByUser = false;

  function open() {
    if (closedByUser) return;
    onStatus("connecting");
    try {
      ws = new WebSocket(url);
    } catch (e) {
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      backoff = BACKOFF_MIN;
      onStatus("open");
      clearInterval(pingTimer);
      pingTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, PING_MS);
    };

    ws.onmessage = (msg) => {
      let ev;
      try {
        ev = JSON.parse(msg.data);
      } catch (e) {
        console.warn("ws: mensagem inválida", msg.data);
        return;
      }
      if (!ev || typeof ev.type !== "string") return;
      if (ev.type === "pong") return;
      try {
        onEvent(ev);
      } catch (e) {
        console.error("ws: erro ao processar evento", ev, e);
      }
    };

    ws.onclose = () => {
      clearInterval(pingTimer);
      pingTimer = null;
      ws = null;
      onStatus("closed");
      scheduleReconnect();
    };

    ws.onerror = () => {
      // onclose dispara logo em seguida; nada a fazer aqui
    };
  }

  function scheduleReconnect() {
    if (closedByUser || reconnectTimer) return;
    const wait = backoff;
    backoff = Math.min(backoff * 2, BACKOFF_MAX);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      open();
    }, wait);
  }

  open();

  return {
    close() {
      closedByUser = true;
      clearInterval(pingTimer);
      clearTimeout(reconnectTimer);
      if (ws) ws.close();
    },
  };
}

function defaultUrl() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws`;
}

/**
 * mcpp-client.js — Uniform MCP / MCP++ JavaScript SDK
 * =====================================================
 *
 * A single, dependency-free client that talks to the hierarchical MCP tool
 * facade shared by ipfs_kit_py, ipfs_datasets_py and ipfs_accelerate_py, over a
 * PLUGGABLE transport:
 *
 *   - HttpTransport   : JSON-RPC 2.0 over HTTP POST (default, browser + Node).
 *   - Libp2pTransport : MCP++ over libp2p using the `/mcp+p2p/1.0.0` protocol
 *                       with u32 big-endian length-prefixed JSON frames. It
 *                       reuses an EXISTING libp2p node/session (e.g. SwissKnife's
 *                       `MCPp2pSession`) so no libp2p dependency is bundled here.
 *
 * Hierarchical tool schema
 * ------------------------
 * The three servers expose a lazy hierarchical facade: `tools/list` returns 4
 * meta-tools (`tools_list_categories`, `tools_list_tools`, `tools_get_schema`,
 * `tools_dispatch`) plus flat `<category>.<tool>` descriptors carrying only a
 * one-line description (full schemas are fetched lazily via `tools_get_schema`).
 * `tools/call` accepts a bare tool name, a dotted `<category>.<tool>` name, or a
 * `tools_dispatch` meta call. This client provides first-class helpers for all
 * of that: `listCategories()`, `listToolsInCategory()`, `getToolSchema()`,
 * `dispatch()`, and a `callTool()` that transparently accepts dotted names.
 *
 * Wire framing
 * ------------
 * The libp2p frame codec mirrors the Python reference implementation
 * (ipfs_accelerate_py/mcp_server/mcplusplus/p2p_framing.py): each frame is
 * `uint32_be(byteLength(json)) || utf8(json)` where `json` is a compact
 * JSON-RPC 2.0 message. (Python serialises with `ensure_ascii=True`; JS keeps
 * raw UTF-8. Both are valid JSON and the length prefix is computed per-side, so
 * the two implementations interoperate.)
 *
 * @version 1.0.0
 */

(function (root, factory) {
  const mod = factory();
  if (typeof module !== 'undefined' && module.exports) {
    module.exports = mod;
  }
  if (typeof root !== 'undefined' && root) {
    root.MCPPP = mod;
    root.MCPPPClient = mod.MCPPPClient;
  }
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const MCPPP_PROTOCOL_ID = '/mcp+p2p/1.0.0';
  const MCP_PROTOCOL_VERSION = '2024-11-05';
  const DEFAULT_MAX_FRAME_BYTES = 16 * 1024 * 1024; // 16 MiB, matches Python default

  class MCPPPError extends Error {
    constructor(code, message, data) {
      super(message);
      this.name = 'MCPPPError';
      this.code = code;
      this.data = data;
    }
  }

  // ---------------------------------------------------------------------------
  // UTF-8 helpers (browser TextEncoder/TextDecoder, Node Buffer fallback)
  // ---------------------------------------------------------------------------
  const _hasTextEncoder = typeof TextEncoder !== 'undefined';
  const _hasTextDecoder = typeof TextDecoder !== 'undefined';

  function _utf8Encode(str) {
    if (_hasTextEncoder) return new TextEncoder().encode(str);
    return Uint8Array.from(Buffer.from(str, 'utf8'));
  }
  function _utf8Decode(bytes) {
    if (_hasTextDecoder) return new TextDecoder('utf-8').decode(bytes);
    return Buffer.from(bytes).toString('utf8');
  }
  function _delay(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  // ---------------------------------------------------------------------------
  // Framing codec (mirrors p2p_framing.py encode/decode_jsonrpc_frame)
  // ---------------------------------------------------------------------------
  function encodeFrame(obj, maxFrameBytes = DEFAULT_MAX_FRAME_BYTES) {
    const body = _utf8Encode(JSON.stringify(obj));
    if (body.length > maxFrameBytes) {
      throw new MCPPPError(-32001, `frame_too_large:${body.length}>${maxFrameBytes}`);
    }
    const frame = new Uint8Array(4 + body.length);
    new DataView(frame.buffer).setUint32(0, body.length, false); // big-endian
    frame.set(body, 4);
    return frame;
  }

  /** Incremental decoder: push arbitrary byte chunks, get complete JSON objects. */
  class FrameDecoder {
    constructor(maxFrameBytes = DEFAULT_MAX_FRAME_BYTES) {
      this.max = maxFrameBytes;
      this._buf = new Uint8Array(0);
    }
    push(chunk) {
      const bytes = chunk instanceof Uint8Array ? chunk : new Uint8Array(chunk);
      if (bytes.length) {
        const merged = new Uint8Array(this._buf.length + bytes.length);
        merged.set(this._buf, 0);
        merged.set(bytes, this._buf.length);
        this._buf = merged;
      }
      const out = [];
      while (this._buf.length >= 4) {
        const declared = new DataView(
          this._buf.buffer,
          this._buf.byteOffset,
          4,
        ).getUint32(0, false);
        if (declared > this.max) {
          throw new MCPPPError(-32001, `frame_too_large:${declared}>${this.max}`);
        }
        if (this._buf.length < 4 + declared) break; // incomplete body
        const body = this._buf.subarray(4, 4 + declared);
        out.push(JSON.parse(_utf8Decode(body)));
        this._buf = this._buf.slice(4 + declared);
      }
      return out;
    }
  }

  // ---------------------------------------------------------------------------
  // Transports — each exposes: async request(reqObj) -> respObj
  //                            async requestBatch(reqArray) -> respArray
  // ---------------------------------------------------------------------------

  /** JSON-RPC 2.0 over HTTP POST. */
  class HttpTransport {
    constructor(endpoint, options = {}) {
      this.endpoint = endpoint;
      this.fetch =
        options.fetchImpl ||
        (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null);
      this.headers = options.headers || {};
      this.timeoutMs = options.timeout || options.timeoutMs || 30000;
      this.retries = Math.max(1, options.retries || 3);
      if (!this.fetch) {
        throw new MCPPPError(-32603, 'No fetch implementation available for HttpTransport');
      }
    }
    get type() {
      return 'http';
    }
    async request(reqObj) {
      return await this._post(reqObj);
    }
    async requestBatch(reqArray) {
      return await this._post(reqArray);
    }
    async _post(body) {
      let lastError;
      for (let attempt = 0; attempt < this.retries; attempt++) {
        try {
          const controller =
            typeof AbortController !== 'undefined' ? new AbortController() : null;
          const timer = controller
            ? setTimeout(() => controller.abort(), this.timeoutMs)
            : null;
          const res = await this.fetch(this.endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', ...this.headers },
            body: JSON.stringify(body),
            signal: controller ? controller.signal : undefined,
          });
          if (timer) clearTimeout(timer);
          if (!res.ok) {
            throw new MCPPPError(-32603, `HTTP ${res.status}: ${res.statusText}`);
          }
          return await res.json();
        } catch (err) {
          lastError = err;
          if (attempt < this.retries - 1) await _delay(Math.pow(2, attempt) * 250);
        }
      }
      throw lastError instanceof MCPPPError
        ? lastError
        : new MCPPPError(-32603, String((lastError && lastError.message) || lastError));
    }
  }

  /**
   * MCP++ over libp2p (protocol id `/mcp+p2p/1.0.0`).
   *
   * Construct with EITHER:
   *   - { session } : an object exposing `async sendRequest(reqObj) -> respObj`
   *                   (e.g. SwissKnife's `MCPp2pSession`). Recommended path — it
   *                   already handles the u32 framing, id correlation and the
   *                   MCP handshake.
   *   - { stream }  : a raw duplex libp2p stream `{ read() -> chunk, write(bytes) }`.
   *                   This transport then applies the frame codec itself.
   */
  class Libp2pTransport {
    constructor(options = {}) {
      this.session = options.session || null;
      this.stream = options.stream || null;
      this.max = options.maxFrameBytes || DEFAULT_MAX_FRAME_BYTES;
      if (!this.session && !this.stream) {
        throw new MCPPPError(-32603, 'Libp2pTransport requires { session } or { stream }');
      }
      this._decoder = new FrameDecoder(this.max);
      this._pending = [];
    }
    get type() {
      return 'libp2p';
    }
    get protocolId() {
      return MCPPP_PROTOCOL_ID;
    }
    async request(reqObj) {
      if (this.session) return await this.session.sendRequest(reqObj);
      await this.stream.write(encodeFrame(reqObj, this.max));
      if (reqObj.id === undefined || reqObj.id === null) return undefined; // notification
      return await this._readMatching(reqObj.id);
    }
    async requestBatch(reqArray) {
      const out = [];
      for (const req of reqArray) out.push(await this.request(req));
      return out;
    }
    async _readMatching(id) {
      for (;;) {
        const idx = this._pending.findIndex((m) => m && m.id === id);
        if (idx >= 0) return this._pending.splice(idx, 1)[0];
        const chunk = await this.stream.read();
        if (!chunk) throw new MCPPPError(-32603, 'libp2p stream closed before response');
        for (const obj of this._decoder.push(chunk)) this._pending.push(obj);
      }
    }
  }

  // ---------------------------------------------------------------------------
  // Unwrap an MCP CallToolResult envelope back to the raw tool payload.
  // ---------------------------------------------------------------------------
  function unwrapToolResult(result) {
    if (
      result &&
      typeof result === 'object' &&
      !Array.isArray(result) &&
      Array.isArray(result.content) &&
      'structuredContent' in result
    ) {
      const sc = result.structuredContent;
      if (
        sc &&
        typeof sc === 'object' &&
        !Array.isArray(sc) &&
        Object.keys(sc).length === 1 &&
        'result' in sc
      ) {
        return sc.result;
      }
      return sc;
    }
    return result;
  }

  // ---------------------------------------------------------------------------
  // The client
  // ---------------------------------------------------------------------------
  class MCPPPClient {
    /**
     * @param {string|object} transportOrEndpoint - an endpoint URL string (uses
     *   HttpTransport) OR any transport object exposing `request(reqObj)`.
     * @param {object} [options] - { clientInfo, transport, ...HttpTransport opts }
     */
    constructor(transportOrEndpoint, options = {}) {
      if (options.transport && typeof options.transport.request === 'function') {
        this.transport = options.transport;
      } else if (typeof transportOrEndpoint === 'string') {
        this.transport = new HttpTransport(transportOrEndpoint, options);
      } else if (
        transportOrEndpoint &&
        typeof transportOrEndpoint.request === 'function'
      ) {
        this.transport = transportOrEndpoint;
      } else {
        throw new MCPPPError(-32603, 'MCPPPClient requires an endpoint string or a transport');
      }
      this._id = 0;
      this.clientInfo = options.clientInfo || { name: 'mcpp-js-client', version: '1.0.0' };
    }

    /** Low-level JSON-RPC call. */
    async _rpc(method, params = {}) {
      const req = { jsonrpc: '2.0', id: ++this._id, method, params };
      const res = await this.transport.request(req);
      if (!res) throw new MCPPPError(-32603, `No response for ${method}`);
      if (res.error) throw new MCPPPError(res.error.code, res.error.message, res.error.data);
      return res.result;
    }

    /** MCP initialize handshake (base-MCP / MCP++ capability negotiation). */
    async initialize() {
      return await this._rpc('initialize', {
        protocolVersion: MCP_PROTOCOL_VERSION,
        capabilities: {},
        clientInfo: this.clientInfo,
      });
    }

    async ping() {
      return await this._rpc('ping', {});
    }

    /** Returns the raw tools/list array (meta-tools + flat `<category>.<tool>`). */
    async listTools() {
      const result = await this._rpc('tools/list', {});
      if (result && Array.isArray(result.tools)) return result.tools;
      if (Array.isArray(result)) return result;
      return [];
    }

    /**
     * Call any tool by name. Accepts a bare name, a dotted `<category>.<tool>`
     * name, or one of the meta-tool names — the server resolves all three.
     */
    async callTool(name, args = {}) {
      const result = await this._rpc('tools/call', { name, arguments: args });
      return unwrapToolResult(result);
    }

    // ---- Hierarchical facade helpers (meta-tools) ----

    /** List tool categories; `{ categories: [{ name, tool_count? }], ... }`. */
    async listCategories(includeCount = true) {
      return await this.callTool('tools_list_categories', { include_count: includeCount });
    }

    /** List the tools inside one category; `{ tools: [{ name, description }], ... }`. */
    async listToolsInCategory(category) {
      return await this.callTool('tools_list_tools', { category });
    }

    /**
     * Lazily fetch a single tool's full JSON schema.
     * @param {string|object} nameOrTool - a tool name string, or `{ name }` /
     *   `{ category, tool }` selector object.
     */
    async getToolSchema(nameOrTool) {
      const params =
        typeof nameOrTool === 'string' ? { name: nameOrTool } : nameOrTool || {};
      return await this.callTool('tools_get_schema', params);
    }

    /** Dispatch a tool inside a category via the `tools_dispatch` meta-tool. */
    async dispatch(category, tool, params = {}) {
      return await this.callTool('tools_dispatch', { category, tool, params });
    }

    // ---- Convenience constructors ----

    /** Build a client that speaks JSON-RPC over HTTP. */
    static overHttp(endpoint, options = {}) {
      return new MCPPPClient(new HttpTransport(endpoint, options), options);
    }

    /**
     * Build a client that speaks MCP++ over libp2p, reusing an existing session
     * (e.g. SwissKnife's `MCPp2pSession`) or a raw duplex stream.
     */
    static overLibp2p(sessionOrOpts, options = {}) {
      const t =
        sessionOrOpts && typeof sessionOrOpts.sendRequest === 'function'
          ? new Libp2pTransport({ session: sessionOrOpts, ...options })
          : new Libp2pTransport(sessionOrOpts || {});
      return new MCPPPClient(t, options);
    }
  }

  return {
    MCPPP_PROTOCOL_ID,
    MCP_PROTOCOL_VERSION,
    DEFAULT_MAX_FRAME_BYTES,
    MCPPPError,
    encodeFrame,
    FrameDecoder,
    HttpTransport,
    Libp2pTransport,
    unwrapToolResult,
    MCPPPClient,
  };
});

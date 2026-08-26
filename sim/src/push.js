// Push layers: Prometheus remote-write (snappy+protobuf via prometheus-remote-write)
// and Loki JSON push.

import { pushTimeseries } from "prometheus-remote-write";

export function makePromPusher(url) {
  return async function push(samples) {
    if (!samples.length) return { ok: true, count: 0 };
    const res = await pushTimeseries(samples, { url });
    if (res.status && res.status >= 300) {
      throw new Error(`remote-write status ${res.status}`);
    }
    return { ok: true, count: samples.length };
  };
}

export function makeLokiPusher(url) {
  return async function push(lines) {
    if (!lines.length) return { ok: true, count: 0 };
    // group lines by identical label sets (Loki requires one values array per stream)
    const streams = new Map();
    for (const { stream, line } of lines) {
      const key = JSON.stringify(stream);
      if (!streams.has(key)) streams.set(key, { stream, values: [] });
      streams.get(key).values.push([String(Date.now() * 1e6), line]);
    }
    const body = JSON.stringify({ streams: [...streams.values()] });
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
    if (!res.ok) throw new Error(`loki push failed: ${res.status} ${await res.text()}`);
    return { ok: true, count: lines.length };
  };
}

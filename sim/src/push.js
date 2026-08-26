// Push layers: Prometheus remote-write (snappy+protobuf via prometheus-remote-write)
// and Loki JSON push.
//
// Both support optional HTTP basic auth — required by Grafana Cloud
// (user id + glc_ API key as password). Local stacks pass no auth.

import { pushTimeseries } from "prometheus-remote-write";

export function makePromPusher(url, auth) {
  return async function push(samples) {
    if (!samples.length) return { ok: true, count: 0 };
    const opts = { url };
    if (auth && auth.username) {
      // the lib implements basic auth itself (its primary target IS Grafana Cloud)
      opts.auth = { username: auth.username, password: auth.password };
    }
    const res = await pushTimeseries(samples, opts);
    if (res.status && res.status >= 300) {
      throw new Error(`remote-write status ${res.status}`);
    }
    return { ok: true, count: samples.length };
  };
}

export function basicAuthHeader(username, password) {
  return `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}`;
}

export function makeLokiPusher(url, auth) {
  const headers = { "Content-Type": "application/json" };
  if (auth && auth.username) {
    headers.Authorization = basicAuthHeader(auth.username, auth.password);
  }
  return async function push(lines) {
    if (!lines.length) return { ok: true, count: 0 };
    // group lines by identical label sets (Loki requires one values array per stream)
    const streams = new Map();
    const now = String(Date.now() * 1e6);
    for (const { stream, line } of lines) {
      const key = JSON.stringify(stream);
      if (!streams.has(key)) streams.set(key, { stream, values: [] });
      streams.get(key).values.push([now, line]);
    }
    const body = JSON.stringify({ streams: [...streams.values()] });
    const res = await fetch(url, { method: "POST", headers, body });
    if (!res.ok) throw new Error(`loki push failed: ${res.status} ${await res.text()}`);
    return { ok: true, count: lines.length };
  };
}

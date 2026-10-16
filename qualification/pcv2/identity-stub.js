// Loopback stand-in for the identity directory an isolated PDS needs:
//   POST /<did>            store the PLC operation the PDS signs and submits
//   GET  /<did>            the did:plc document built from that operation
//   GET  /<did>/data       the PLC "data" form of the same document
//   GET  /<did>/log/last   the last stored operation
//   GET  /xrpc/com.atproto.identity.resolveHandle?handle=<h>
//                          the DID whose document lists at://<h> in alsoKnownAs
// It runs unmodified Node inside the pinned PDS image, keeps state in memory,
// has no persistence, and is reachable only on the isolated Docker network and
// its published loopback port. Nothing here is a real PLC: operations are not
// validated or signed-checked, and there is no history.
"use strict";
const http = require("http");

const operations = new Map();

function document(did, op) {
  const verificationMethod = Object.entries(op.verificationMethods || {}).map(([name, key]) => ({
    id: `${did}#${name}`,
    type: "Multikey",
    controller: did,
    publicKeyMultibase: String(key).replace(/^did:key:/, ""),
  }));
  const service = Object.entries(op.services || {}).map(([name, value]) => ({
    id: `#${name}`,
    type: value.type,
    serviceEndpoint: value.endpoint,
  }));
  return {
    "@context": [
      "https://www.w3.org/ns/did/v1",
      "https://w3id.org/security/multikey/v1",
      "https://w3id.org/security/suites/secp256k1-2019/v1",
    ],
    id: did,
    alsoKnownAs: op.alsoKnownAs || [],
    verificationMethod,
    service,
  };
}

function send(response, status, body, type = "application/json") {
  const encoded = Buffer.from(JSON.stringify(body));
  response.writeHead(status, { "content-type": type, "content-length": encoded.length });
  response.end(encoded);
}

http.createServer((request, response) => {
  const url = new URL(request.url, "http://stub.invalid");
  const segments = url.pathname.split("/").filter((part) => part !== "").map(decodeURIComponent);
  if (request.method === "GET" && url.pathname === "/xrpc/com.atproto.identity.resolveHandle") {
    const handle = (url.searchParams.get("handle") || "").toLowerCase();
    for (const [did, op] of operations) {
      if ((op.alsoKnownAs || []).some((alias) => String(alias).toLowerCase() === `at://${handle}`)) {
        return send(response, 200, { did });
      }
    }
    return send(response, 400, { error: "InvalidRequest", message: "Unable to resolve handle" });
  }
  if (request.method === "GET" && url.pathname === "/_health") return send(response, 200, { ok: true, dids: operations.size });
  if (segments.length === 0 || !segments[0].startsWith("did:plc:")) return send(response, 404, { message: "not found" });
  const did = segments[0];
  if (request.method === "POST" && segments.length === 1) {
    let body = "";
    request.on("data", (chunk) => { body += chunk; });
    request.on("end", () => {
      try {
        const op = JSON.parse(body);
        if (op.type !== "plc_operation") return send(response, 400, { message: "unsupported operation type" });
        operations.set(did, op);
        send(response, 200, {});
      } catch {
        send(response, 400, { message: "malformed operation" });
      }
    });
    return;
  }
  const op = operations.get(did);
  if (op === undefined) return send(response, 404, { message: "DID not registered" });
  if (request.method === "GET" && segments.length === 1) return send(response, 200, document(did, op), "application/did+ld+json");
  if (request.method === "GET" && segments[1] === "data") {
    return send(response, 200, { did, rotationKeys: op.rotationKeys, verificationMethods: op.verificationMethods, alsoKnownAs: op.alsoKnownAs, services: op.services });
  }
  if (request.method === "GET" && segments[1] === "log" && segments[2] === "last") return send(response, 200, op);
  return send(response, 404, { message: "not found" });
}).listen(2582, "0.0.0.0");

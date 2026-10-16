import { createServer, type Server } from "node:http";

export type LoopbackCallbackServer = Readonly<{
  callbackUrl: URL;
  completion: Promise<void>;
  close: () => Promise<void>;
}>;

export async function startLoopbackCallbackServer(
  expected: URL,
  consume: (callback: URL) => Promise<void>,
  timeoutMilliseconds = 30 * 60 * 1000,
): Promise<LoopbackCallbackServer> {
  if (expected.protocol !== "http:" || expected.hostname !== "127.0.0.1") {
    throw new Error("OAuth callback listener requires explicit IPv4 loopback");
  }

  let settle!: () => void;
  let refuse!: (error: Error) => void;
  const completion = new Promise<void>((resolve, reject) => {
    settle = resolve;
    refuse = reject;
  });
  let consumed = false;
  let timer: NodeJS.Timeout;
  const server = createServer(async (request, response) => {
    const requestUrl = new URL(request.url ?? "/", expected.origin);
    if (request.method !== "GET" || requestUrl.pathname !== expected.pathname) {
      response.writeHead(404, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
      response.end("Not found.\n");
      return;
    }
    if (consumed) {
      response.writeHead(409, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
      response.end("This authorization callback was already consumed.\n");
      return;
    }
    consumed = true;
    try {
      await consume(requestUrl);
      response.writeHead(200, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
      response.end("Juniper bootstrap authorization completed. You may close this tab.\n");
      clearTimeout(timer);
      settle();
    } catch (error) {
      response.writeHead(400, { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" });
      response.end("Juniper bootstrap authorization did not complete. Check the terminal for the bounded reason, then close this tab.\n");
      clearTimeout(timer);
      refuse(error instanceof Error ? error : new Error("OAuth callback refused"));
    } finally {
      server.close();
    }
  });
  await listen(server, Number(expected.port));
  const address = server.address();
  if (!address || typeof address === "string") {
    server.close();
    throw new Error("OAuth callback listener address unavailable");
  }
  const callbackUrl = new URL(expected.toString());
  callbackUrl.port = String(address.port);
  timer = setTimeout(() => {
    server.close();
    refuse(new Error("OAuth callback timed out"));
  }, timeoutMilliseconds);
  timer.unref();
  return {
    callbackUrl,
    completion,
    close: async () => {
      clearTimeout(timer);
      await close(server);
    },
  };
}

async function listen(server: Server, port: number): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => {
      server.removeListener("error", reject);
      resolve();
    });
  });
}

async function close(server: Server): Promise<void> {
  if (!server.listening) return;
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

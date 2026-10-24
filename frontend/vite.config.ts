import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { demoBff } from "./demoBff";

export default defineConfig(({ command, mode }) => ({
  plugins: [react(), demoBff()],
  server: {
    host: "127.0.0.1",
    proxy: {
      // Only the explicit local demo reads use the isolated read-only runtime.
      // All shared APIs retain their existing 8000 backend and identity headers.
      ...(command === "serve" && mode === "demo" && process.env.VITE_ORDERS_DEMO === "1"
        ? { "/v1/demo/orders": "http://127.0.0.1:8001" } : {}),
      "/dev/p1": `http://127.0.0.1:${process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000'}`,
      "/v1/messages": `http://127.0.0.1:${process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000'}`,
      "/v1/contexts": `http://127.0.0.1:${process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000'}`,
      "/v1/attachments": `http://127.0.0.1:${process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000'}`,
      "/v1/communications": {
        target: `http://127.0.0.1:${process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000'}`,
        configure(proxy) {
          proxy.on("proxyReq", (request, incoming) => {
            const key = process.env.MOUMANTAI_ISOLATED_E2E_KEY;
            if (process.env.MOUMANTAI_ISOLATED_E2E === "1" && key && incoming.method === "POST" &&
              incoming.url?.startsWith("/v1/communications/requests")) {
              request.setHeader("X-Isolated-E2E-Key", key);
              const managerId = process.env.MOUMANTAI_ISOLATED_E2E_MANAGER_ID;
              if (managerId) request.setHeader("X-Actor-ID", managerId);
            }
          });
        },
      },
      "/v1/recovery": {
        target: `http://127.0.0.1:${process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000'}`,
        configure(proxy) {
          proxy.on("proxyReq", (request, incoming) => {
            const key = process.env.MOUMANTAI_ISOLATED_E2E_KEY;
            if (process.env.MOUMANTAI_ISOLATED_E2E === "1" && key && incoming.url?.startsWith("/v1/recovery/")) {
              request.setHeader("X-Isolated-E2E-Key", key);
              const managerId = process.env.MOUMANTAI_ISOLATED_E2E_MANAGER_ID;
              if (managerId && incoming.url.startsWith("/v1/recovery/plans/")) {
                // Local synthetic actor identity is chosen by the server, never by browser headers.
                request.setHeader("X-Actor-ID", managerId);
              }
            }
          });
        },
      },
      "/v1": `http://127.0.0.1:${process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000'}`,
      "/health": `http://127.0.0.1:${process.env.MOUMANTAI_LOCAL_API_PORT ?? '8000'}`,
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    testTimeout: 15000,
  },
}));

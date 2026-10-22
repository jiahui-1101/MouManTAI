import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    proxy: {
      "/dev/p1": "http://127.0.0.1:8000",
      "/v1/messages": "http://127.0.0.1:8000",
      "/v1/recovery": {
        target: "http://127.0.0.1:8000",
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
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});

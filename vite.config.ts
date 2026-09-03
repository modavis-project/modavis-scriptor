import tailwindcss from "@tailwindcss/postcss";
import vinext from "vinext";
import { defineConfig } from "vite";

const workerConfig = {
  main: "vinext/server/fetch-handler",
  compatibility_flags: ["nodejs_compat"],
  assets: { binding: "ASSETS" },
  vars: { GRAPHICS_API_URL: process.env.GRAPHICS_API_URL || "http://127.0.0.1:8010" },
};

export default defineConfig(async () => {
  process.env.WRANGLER_WRITE_LOGS ??= "false";
  process.env.WRANGLER_LOG_PATH ??= ".wrangler/logs";
  process.env.MINIFLARE_REGISTRY_PATH ??= ".wrangler/registry";
  const { cloudflare } = await import("@cloudflare/vite-plugin");
  return {
    css: { postcss: { plugins: [tailwindcss()] } },
    plugins: [
      vinext(),
      cloudflare({
        viteEnvironment: { name: "rsc", childEnvironments: ["ssr"] },
        config: workerConfig,
      }),
    ],
  };
});

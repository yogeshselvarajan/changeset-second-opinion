import { defineConfig } from "@hey-api/openapi-ts";

// Regenerate (integration owner only):
//   npx @hey-api/openapi-ts -f openapi-ts.config.ts
export default defineConfig({
  input: "../backend/openapi/v1.json",
  output: "src/api",
  plugins: ["@hey-api/client-fetch", { name: "@tanstack/react-query", queryKeys: true }],
});

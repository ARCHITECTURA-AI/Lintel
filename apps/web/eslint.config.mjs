import next from "eslint-config-next";

const config = [...next, { ignores: [".next/**", "node_modules/**", "e2e/**", "src/lib/schemas.gen.ts"] }];

export default config;

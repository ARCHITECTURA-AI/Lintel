import next from "eslint-config-next";

export default [...next, { ignores: [".next/**", "node_modules/**", "e2e/**", "src/lib/schemas.gen.ts"] }];

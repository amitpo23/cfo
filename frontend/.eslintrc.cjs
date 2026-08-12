/**
 * Frontend static-analysis contract.
 *
 * TypeScript already runs with strict/noUnused* in `npm run build`; ESLint
 * adds React Hooks correctness and makes the existing `npm run lint` script
 * an executable QA gate instead of a permanently missing configuration.
 */
module.exports = {
  root: true,
  env: {
    browser: true,
    es2022: true,
    node: true,
  },
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react-hooks', 'react-refresh'],
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', 'node_modules'],
  rules: {
    // The repository has explicit, typed API boundary values where `any` is
    // still intentional.  Strict TypeScript remains the type-safety gate.
    '@typescript-eslint/no-explicit-any': 'off',
    '@typescript-eslint/no-unused-vars': [
      'error',
      { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
    ],
    // Vite HMR guidance, not a correctness property; several established
    // modules intentionally export small helpers next to components.
    'react-refresh/only-export-components': 'off',
  },
};

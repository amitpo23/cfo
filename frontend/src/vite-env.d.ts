/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_BASE_URL: string;
  readonly VITE_APP_NAME: string;
  readonly VITE_APP_VERSION: string;
  readonly VITE_ENABLE_AI_INSIGHTS: string;
  readonly VITE_ENABLE_FORECASTING: string;
  readonly VITE_ENABLE_DARK_MODE: string;
  readonly VITE_AUTH_BYPASS: string;
  readonly VITE_GOOGLE_CLIENT_ID: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

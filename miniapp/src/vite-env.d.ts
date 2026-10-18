/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** "serverless" — build for Telegram Serverless (see vite.config.ts). */
  readonly VITE_BACKEND?: string
}

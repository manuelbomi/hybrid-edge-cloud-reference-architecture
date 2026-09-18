/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of `cloud/ingest_api.py` (e.g. http://localhost:8080). */
  readonly VITE_INGEST_API_URL?: string;
  /** Base URL of `edge/local_api.py` (e.g. http://localhost:8000). */
  readonly VITE_EDGE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

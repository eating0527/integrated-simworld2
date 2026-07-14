/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_NTPU_ORIGIN_LAT?: string;
  readonly VITE_NTPU_ORIGIN_LON?: string;
  readonly VITE_NTPU_ORIGIN_ALT?: string;
  readonly VITE_NTPU_SCENE_OFFSET_X?: string;
  readonly VITE_NTPU_SCENE_OFFSET_Y?: string;
  readonly VITE_NTPU_SCENE_OFFSET_Z?: string;
  readonly VITE_NYCU_ORIGIN_LAT?: string;
  readonly VITE_NYCU_ORIGIN_LON?: string;
  readonly VITE_NYCU_ORIGIN_ALT?: string;
  readonly VITE_NYCU_SCENE_OFFSET_X?: string;
  readonly VITE_NYCU_SCENE_OFFSET_Y?: string;
  readonly VITE_NYCU_SCENE_OFFSET_Z?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

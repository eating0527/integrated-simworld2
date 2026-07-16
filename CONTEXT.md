# ISS_UNET Noise/GPS Context

這個 context 定義 ISS_UNET「Noise with GPS」流程中，雜訊測量與 GPS 路徑位置的共同語言。

## Language

**有效雜訊值**：
`noise_floor_db` 小於 -1 dB 的雜訊測量值；大於或等於 -1 dB 的讀值不被視為可用測量。
_Avoid_: 門檻以上雜訊值、補零、截斷值

**位置保留點**：
已與 GPS 時間對齊的路徑位置，即使沒有有效雜訊值仍保留；它不代表有效的雜訊測量。
_Avoid_: 有效雜訊點

**雜訊門檻過濾**：
將 `noise_floor_db` 大於或等於 -1 dB 的測量排除在計算之外；此規則可由每次 ISS_UNET 請求的選項控制，預設啟用。
_Avoid_: 補零、門檻值截斷

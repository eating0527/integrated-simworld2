# Control Mode Isolation and GPS Freshness Simplification

Status: ready-for-agent

## Problem Statement

操作人員在採樣面板切換 Bound 與 Independent 控制方式時，前端目前會把其中一個 child 的未收尾狀態廣泛地鎖住另一個服務的控制；切換按鈕也可能直接 disabled，沒有指出必須先完成哪個任務。這與 AP3／無人機遙控器及 Raspberry Pi／Noise 控制平面是獨立硬體的實際操作方式不符。

此外，沒有連接 UAV 時 GPS recorder 可以正常執行但沒有 GPS row。現有的資料新鮮度判斷會把這個測試情境誤報為 Reconciling 或 Presumed running，妨礙正常測試。重新整理 frontend 後，未收尾 Independent Capture 也必須重新顯示並可控制，而不是出現 session 或狀態遺失的操作體驗。

## Solution

引入明確的 Control Mode：Bound 與 Independent。Control Mode 只決定控制與狀態投影，不改寫 mission 或背景硬體服務。

Independent Control Mode 下，GPS 與 Noise 是獨立採樣：彼此的 mission 狀態不會禁用對方的 Start、Stop 或 Noise mode controls。Bound Control Mode 維持既有 shared `mission_id`、雙 preflight、獨立 child lifecycle 與 Stop All 流程。Bound Mission 和 Independent Capture 不可同時有未收尾任務。

使用者按 Bind services 時，系統應檢查未收尾任務。若任何 GPS 或 Noise 任務仍在執行、停止、reconciling、Retry Stop 或 Upload Pending，保留原模式並顯示明確提示，不自動停止、不要求二次確認。所有任務終止後才切換到另一種 Control Mode 的乾淨控制面板。

乾淨控制面板不恢復舊 mission 的 child 狀態、不建立空 mission、也不啟動硬體；它保留 Device Health 及每個服務跨模式最近一次 mission 的開始時間與 `mission_id` 後五碼。GPS recorder 不再因為固定時間沒有資料而視為服務異常；AP3 明確離線與 recorder process 結束仍維持既有安全處理。

## User Stories

1. As an 操作人員, I want Independent Control Mode to let GPS start while Noise is active, so that independent hardware can be controlled concurrently.
2. As an 操作人員, I want Independent Control Mode to let Noise start while GPS is active, so that GPS state does not block Raspberry Pi work.
3. As an 操作人員, I want GPS Stop to affect only GPS in Independent Control Mode, so that it never stops or locks Noise.
4. As an 操作人員, I want Noise Stop to affect only Noise in Independent Control Mode, so that it never stops or locks GPS.
5. As an 操作人員, I want Test mode and USRP mode to remain selectable while GPS is active, so that AP3 activity does not constrain Raspberry Pi mode selection.
6. As an 操作人員, I want Noise mode controls locked only by Noise's own unresolved state or Raspberry Pi health, so that I understand the real dependency.
7. As an 操作人員, I want Bound Capture to retain one shared `mission_id`, so that GPS and Noise artifacts remain associated.
8. As an 操作人員, I want a Bound Mission to retain independent child lifecycles, so that one child failure does not stop its healthy sibling.
9. As an 操作人員, I want Start Bound Capture rejected while an Independent GPS or Noise mission is unresolved, so that hardware ownership cannot mix modes.
10. As an 操作人員, I want Start UAV and Start USRP rejected while a Bound Mission is unresolved, so that a Bound Mission cannot be mixed with an Independent Capture.
11. As an 操作人員, I want Bind services to remain clickable when a mission is unresolved, so that I receive an explanation instead of an unexplained disabled control.
12. As an 操作人員, I want a mode switch blocked while GPS is unresolved, so that I can stop GPS before changing the control projection.
13. As an 操作人員, I want a mode switch blocked while Noise is unresolved, so that I can stop or finish uploading Noise before changing the control projection.
14. As an 操作人員, I want a mode switch blocked while both GPS and Noise are unresolved, so that neither active service is hidden.
15. As an 操作人員, I want a Bound Mission switch block to say `請先停止當前任務。`, so that the action is clear.
16. As an 操作人員, I want an unresolved GPS switch block to say `請先停止 GPS 任務。`, so that I know what to stop.
17. As an 操作人員, I want an unresolved Noise switch block to say `請先停止 Noise 任務。`, so that I know what to stop.
18. As an 操作人員, I want an unresolved GPS and Noise switch block to say `請先停止 GPS 與 Noise 任務。`, so that I see every blocking service.
19. As an 操作人員, I want Upload Pending to say `請先等待 Noise 上傳。`, so that I know a service has stopped but its artifact is not complete.
20. As an 操作人員, I want Control Mode switching to perform no automatic Stop and show no confirmation dialog, so that switching cannot cause an unexpected hardware action.
21. As an 操作人員, I want Completed, Failed, and Resume Timeout results to permit a mode switch, so that terminal history never blocks future work.
22. As an 操作人員, I want Independent to be the default when no mission is unresolved, so that I can begin independent testing immediately.
23. As an 操作人員, I want an active Bound Mission restored in Bound Control Mode after frontend reload, so that it remains visible and controllable.
24. As an 操作人員, I want active Independent GPS and Noise missions restored after frontend reload, so that they remain visible and controllable without a session-state error.
25. As an 操作人員, I want terminal mission child states hidden after entering a clean panel, so that old errors and actions do not look current.
26. As an 操作人員, I want both clean panels to display each service's latest mission start time and ID suffix, so that I retain lightweight historical context.
27. As an 操作人員, I want a Bound Mission's shared start time and ID suffix displayed separately in both GPS and Noise sections, so that the shared result is evident without merging the sections.
28. As an 操作人員, I want a missing previous mission shown as `—`, so that Device Health timing is not mistaken for mission history.
29. As an 操作人員, I want mission and Raspberry Pi health timestamps formatted as `MM/DD HH:mm:ss` in Asia/Taipei, so that every operator sees the same readable time.
30. As an 操作人員, I want the existing Raspberry Pi health timestamp's meaning unchanged, so that a formatting update does not fabricate a successful-reach record.
31. As an 操作人員, I want GPS recording with no GPS rows to remain Running while the recorder and AP3 connection are healthy, so that an unconnected UAV does not break testing.
32. As an 操作人員, I want a normally stopped GPS recorder with only a canonical CSV header to complete, so that no-data tests can finish normally.
33. As an 操作人員, I want AP3 connection loss and recorder process exit to remain explicit failure or recovery signals, so that removing freshness monitoring does not hide genuine hardware faults.
34. As an 操作人員, I want backend restart process adoption to remain out of scope, so that the UI never claims safe control of an unverified GPS recorder.

## Implementation Decisions

- Control Mode is a frontend control projection with `independent` as the idle default. It is not the Bound Mission domain term and it does not mutate persisted mission state.
- The persisted mission model continues to distinguish `target` and `bind`. A Bound Mission has one shared `mission_id`; Independent GPS and Noise captures have their own missions.
- A shared status projection must identify the active control context without merging unrelated terminal child results. It must provide enough data for the frontend to render either a current active projection or a clean panel plus per-service last-mission summaries.
- Unresolved means a child with active execution, uncertain execution, stopping, finalization, upload pending, reconciliation, or retryable stop work. Completed, Failed, and Resume Timeout are terminal and do not block a mode switch.
- Creating a Bound Mission must reject any unresolved Independent Capture. Creating an Independent GPS or Noise mission must reject any unresolved Bound Mission. Within Independent Control Mode, a GPS mission and a Noise mission may proceed independently and concurrently.
- The frontend mode switch remains interactive. It evaluates the status projection and, when blocked, retains the current mode and announces the prescribed localized message. It never sends a Stop request as a side effect of switching.
- A clean panel has idle child controls and current Device Health, but does not rehydrate terminal child phase, file, error, or action state. It displays the most recent mission involving each service across both modes as start time plus the final five characters of its mission identifier.
- When the latest mission is a Bound Mission, GPS and Noise each display the same shared start time and identifier suffix. When a service has no earlier mission, it displays `—`.
- Frontend reload restores unresolved persisted missions and their controls. It does not restore a completed mission as the active control state. Backend restart may still require explicit safe recovery for a local GPS recorder and must not claim ownership from persisted metadata alone.
- The frontend formats prior-mission timestamps and the existing Raspberry Pi health timestamp with the `Asia/Taipei` timezone and `MM/DD HH:mm:ss` format. The backend timestamp fields and their meanings remain unchanged.
- Remove the GPS row-age transition that converts a live GPS recorder with no new rows into Reconciling or Presumed running. Preserve AP3 health failures and recorder process ownership/exit checks as independent safety signals.
- A canonical GPS CSV containing only its header remains a valid artifact when the recorder stops normally.
- Preserve keyboard focus, `aria-expanded`, `aria-controls`, sufficient touch targets, and accessible live error announcements. Mode-switch blocker messages use `role="alert"`.

## Testing Decisions

- Tests assert externally observable status payloads, persisted mission state, enabled/disabled controls, rendered labels, accessible alerts, and Start/Stop API behavior; they do not assert private locks or internal helper calls.
- The primary backend seam is Capture Coordinator public start, stop, retry, and status operations plus their persisted mission state. Coordinator tests cover independent concurrency, cross-mode rejection, clean terminal projection, active projection after status reload, and removal of the GPS freshness transition.
- The primary frontend seam is the telemetry component rendered with status and health responses. Tests cover Independent button eligibility for every relevant GPS and Noise state, Bound eligibility, mode-switch blocker text, clean-panel summaries, timestamp formatting, frontend reload restoration, and keyboard-accessible alerts.
- Existing Capture Coordinator tests and telemetry component tests are prior art. Extend the established fake process, fake Raspberry Pi backend, temporary Capture Store, and Vitest fetch/timer patterns rather than creating lower-level replacement seams.
- Add regression tests proving one active Independent service never disables the other service's Start, Stop, or Noise mode controls; proving mixed active Bound and Independent missions are rejected; and proving switching does not send Stop requests.
- Add regression tests proving no GPS row beyond the previous freshness threshold leaves a healthy recorder Running, while AP3 health loss and recorder exit still surface their existing outcomes.
- Run affected backend tests with the configured Python environment, affected frontend tests, the complete backend suite, the complete frontend suite, and the frontend production build.

## Out of Scope

- Automatic Stop, force-stop, or confirmation dialogs caused by Control Mode switching.
- Backend restart adoption or reattachment to an unverified local GPS recorder process.
- Changing the Raspberry Pi health timestamp's backend schema or interpreting it as a last successful reach timestamp.
- Restoring terminal mission child state, error text, retry controls, or file state into a clean panel.
- Creating a mission, starting hardware, or creating an empty artifact merely by switching Control Mode.
- Changing Bound Mission shared ownership, dual preflight, Best-Effort Stop All, upload retry schedules, or terminal aggregation semantics beyond the removal of GPS row-age freshness as a failure signal.
- A historical mission browser or a full mission history API.

## Further Notes

- This specification supersedes the earlier requirement that Bind and mode controls must always be disabled while either child is active. The new rule keeps cross-mode mission creation exclusive but lets the operator press the mode switch and receive an actionable blocker message.
- Test Noise Capture remains a Raspberry Pi script-based Noise workflow and does not use a USRP B210. It shares the Noise control plane and its mode eligibility rules.
- The implementation must not make a completed/failed historical mission disappear from persistence; it only changes the control-panel projection.
- The selected language and boundaries are recorded in the glossary and ADRs for Control Mode, Independent Capture, mode-switch blockers, reload recovery, and GPS data freshness.

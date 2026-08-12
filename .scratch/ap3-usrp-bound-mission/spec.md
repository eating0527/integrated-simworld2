# AP3 + USRP 綁定任務重構規格

Status: ready-for-agent

## Problem Statement

操作人員目前無法只看前端就可靠判斷 AP3 與 Raspberry Pi／USRP 現在是否可用、在特定量測任務中正在做什麼，以及單邊故障後另一邊是否仍在正常採樣。前端將多種 child state 簡化為 Active 或 Ready，可能把失敗任務誤顯示為 Ready；裝置目前的健康狀態也和歷史任務結果混在一起。

綁定任務雖已具有共用 `mission_id` 與 AP3／USRP 雙 child 結構，但狀態聚合、閒置健康檢查、執行中恢復、Best-Effort Stop、檔案收尾及 Noise 自動上傳仍缺乏一套完整且可持久化的契約。AP3 或 RasPi 斷線時，系統可能無法準確區分程序仍在執行、採樣已中斷、任務可接續或任務已逾期；停止或上傳失敗後，也缺乏一致且安全的前端補救操作。

## Solution

將綁定任務定義為 AP3 與 USRP 共用同一個 `mission_id`，但各自維護獨立的 Connection、Service、File、Phase 與 Error 狀態。Mission Overall State 只負責描述整體生命週期；裝置或檔案的具體異常由各任務子狀態提供，前端再組合為清楚的人類可讀訊息。

系統會把 Device Health 與 Mission Child State 分離。Device Health 回答裝置現在能否參與新任務；Mission Child State 保留特定任務的歷程與結果，裝置之後拔除或恢復都不會改寫已完成任務。

完整交付涵蓋 WF1–WF6，並以 WF1–WF3 作為第一階段 release gate。後續加入執行中監控與 AP3 五分鐘採樣接續、Stop All 與每個 child 的 Retry Stop，以及 Noise 背景上傳與三次有限退避重試。所有任務狀態、恢復期限、停止結果與上傳重試進度都以既有任務持久化資料為準，並沿用鎖定與原子寫入。

## User Stories

1. As an 操作人員, I want to see AP3 Device Health without starting a mission, so that I know whether GPS capture can begin.
2. As an 操作人員, I want to see RasPi Device Health without starting a mission, so that I know whether USRP capture can begin.
3. As an 操作人員, I want Device Health to update without refreshing the page, so that recovery is visible immediately.
4. As an 操作人員, I want Device Health separated from historical mission results, so that reconnecting a device does not rewrite what happened in an earlier mission.
5. As an 操作人員, I want AP3 and USRP to show Connection, Service, File, Phase, and Error independently, so that I can identify the failing subsystem.
6. As an 操作人員, I want the mission badge to use Mission Overall State, so that a failed mission is never summarized as Ready.
7. As an 操作人員, I want a degraded mission to identify GPS or Noise as Failed or Offline, so that `DEGRADED` alone is not ambiguous.
8. As an 操作人員, I want a degraded mission to show what the healthy child is still doing, so that I know whether useful sampling continues.
9. As an 操作人員, I want a warning completion to identify `GPS FAILED` or `NOISE FAILED`, so that I immediately understand which result is missing.
10. As an 操作人員, I want partial GPS data retained after an interruption, so that already captured valid positions remain usable.
11. As an 操作人員, I want partial GPS data labeled as partial, so that it is not mistaken for a complete capture.
12. As an 操作人員, I want independent capture controls when Bind is disabled, so that AP3 or USRP can operate alone.
13. As an 操作人員, I want Bind controls locked while either child is active, so that an executing mission cannot change ownership or mode.
14. As an 操作人員, I want a bound start rejected when AP3 is not ready, so that an invalid mission is not created.
15. As an 操作人員, I want a bound start rejected when RasPi is not ready, so that an invalid mission is not created.
16. As an 操作人員, I want the rejected start to name the unavailable device, so that I can correct the actual problem.
17. As an 操作人員, I want a successful bound start to create one shared mission identifier, so that GPS and Noise artifacts belong to the same measurement.
18. As an 操作人員, I want both child states to carry the shared mission identifier, so that status and files cannot drift into different missions.
19. As an 操作人員, I want AP3 to keep recording if USRP fails after start, so that one failure does not discard healthy GPS data.
20. As an 操作人員, I want USRP to keep recording if AP3 fails after start, so that one failure does not discard healthy Noise data.
21. As an 操作人員, I want the mission to become Degraded after a one-sided start failure, so that the surviving capture remains visible as active.
22. As an 操作人員, I want the mission to become Failed only when neither child can produce a usable result, so that partial success is represented accurately.
23. As an 操作人員, I want active status polling to be single-flight, so that slow requests never accumulate overlapping status calls.
24. As an 操作人員, I want AP3 data freshness monitored during a mission, so that a live recorder process without incoming GPS is not reported as healthy recording.
25. As an 操作人員, I want RasPi disconnection to set USRP Connection to Offline while preserving Presumed running when appropriate, so that an SSH failure does not fabricate a stop.
26. As an 操作人員, I want the unaffected child to continue during a runtime disconnection, so that a bound mission remains useful in degraded mode.
27. As an 操作人員, I want USRP state reconciled after SSH recovery, so that the mission returns to Running only when the remote mission is confirmed.
28. As an 操作人員, I want AP3 to resume the same mission automatically after a short disconnection, so that transient USB or forwarding failures do not split the capture.
29. As an 操作人員, I want AP3 resume to append to the same GPS file, so that existing mission data is never overwritten.
30. As an 操作人員, I want AP3 resume to preserve the original mission identifier, so that GPS and Noise stay bound.
31. As an 操作人員, I want AP3 resume limited to five minutes from the last valid GPS sample, so that a long outage is not hidden as one continuous capture.
32. As an 操作人員, I want AP3 resume to reject an invalid GPS schema, so that append cannot corrupt an existing result.
33. As an 操作人員, I want a resume timeout shown explicitly in the AP3 section, so that I know why a recovered device did not continue the mission.
34. As an 操作人員, I want AP3 Health to return to Ready after a resume timeout without changing the old child result, so that the device can be used in a future mission.
35. As an 操作人員, I want Stop All to attempt AP3 and USRP stop concurrently, so that finalization is not unnecessarily serialized.
36. As an 操作人員, I want one failed stop not to cancel the other stop, so that every controllable child is safely finalized.
37. As an 操作人員, I want Stop All to avoid claiming completion while a remote service may still run, so that uncertain hardware is never misreported as stopped.
38. As an 操作人員, I want the existing child Stop control to become Retry Stop after a stop failure, so that recovery is available without adding a dangerous force-complete action.
39. As an 操作人員, I want Retry Stop to affect only its own child, so that an already stopped sibling is not commanded again.
40. As an 操作人員, I want a stopped child control disabled and labeled Stopped, so that its terminal state is unambiguous.
41. As an 操作人員, I want USRP Retry Stop disabled while RasPi remains offline, so that an impossible action is not offered.
42. As an 操作人員, I want USRP Retry Stop enabled after RasPi reconnects, so that I can safely finish an uncertain remote capture.
43. As an 操作人員, I want GPS files to use one canonical schema, so that recorder, coordinator, stop validation, upload, and consumers agree.
44. As an 操作人員, I want Noise upload to begin automatically after successful USRP finalization, so that normal missions do not require a manual upload step.
45. As an 操作人員, I want upload failure to remain Upload Pending, so that a missing Noise artifact never produces Completed.
46. As an 操作人員, I want failed automatic uploads retried after 5, 15, and 30 seconds, so that transient network failures recover automatically without an infinite loop.
47. As an 操作人員, I want the pending retry text to show `自動重試 N/3 (倒數 s)`, so that I know when the next attempt will begin.
48. As an 操作人員, I want an active automatic retry to show `正在重試 N/3 (經過 s)`, so that I know the request is still running.
49. As an 操作人員, I want intermediate retry failures to advance directly to the next countdown, so that temporary errors do not create noisy transient messages.
50. As an 操作人員, I want `自動重試已用盡` shown only after all three retries fail, so that exhaustion has one clear meaning.
51. As an 操作人員, I want a Manual Retry after automatic retries are exhausted, so that I retain control after external conditions improve.
52. As an 操作人員, I want a manual retry to show `手動重試 (經過 s)`, so that long-running attempts have visible progress.
53. As an 操作人員, I want manual retry not to reset the automatic retry count, so that automatic retry history remains truthful.
54. As an 操作人員, I want retry state restored after a backend restart, so that pending uploads do not silently disappear.
55. As an 操作人員, I want a mission Completed only after both required child results are ready or uploaded, so that completion means all expected artifacts are available.
56. As an 操作人員, I want a mission Completed with Warning when all services are terminal, one child completes, and the other ends failed or incomplete, so that a partial outcome is final but explicit.
57. As an 操作人員, I want a mission kept Finalizing while Noise is Upload Pending, so that a retryable upload is not treated as permanent loss.
58. As an 維護人員, I want capture state updates locked and atomically persisted, so that concurrent status, stop, resume, upload, and callback operations cannot corrupt mission state.
59. As an 維護人員, I want blocking ADB, SSH, process, and upload work bounded by timeouts and moved off async request execution, so that the API remains responsive.
60. As an 維護人員, I want health checks lightweight and diagnostics separate, so that regular monitoring does not repeatedly fetch heavy logs.

## Implementation Decisions

### Delivery and domain boundaries

- This is one complete WF1–WF6 specification. WF1–WF3 form the first release gate and must pass their automated and integration acceptance criteria before WF4 begins. WF5 starts only after runtime recovery is stable; WF6 starts only after stop and finalization behavior is stable.
- Use the glossary terms Bound Mission, Device Health, Mission Child State, Retry Stop, AP3 Capture Resume, Resume Timeout, Degraded Mission, Completed with Warning, and Partial GPS Result.
- A Bound Mission means shared ownership through one `mission_id`; it does not mean time-aligned rows, exact start/stop synchronization, or coupled child lifecycles.
- AP3 and USRP maintain independent Connection, Service, File, Phase, Error, path, and process or remote identity information. A child failure never rolls back or automatically stops its healthy sibling.

### WF1 — State contract and aggregation

- Preserve the established Connection values Ready, Offline, and Unknown.
- Preserve the established Service values Idle, Starting, Running, Presumed running, Stopping, Stopped, and Failed. Presumed running means control-plane contact was lost while the service may still be active; it must never be interpreted as Stopped.
- Preserve the established File values None, Recording, Finalizing, Ready, Upload Pending, Uploaded, and Failed. A Partial GPS Result is represented by a finalized, available GPS file together with a failed AP3 service or resume-timeout phase and an explanatory error; the available file must not be discarded merely because capture was incomplete.
- Add explicit phases for stop failure and resume timeout. Stop failure makes the child eligible for Retry Stop; a general execution failure does not automatically make Stop available. Reconciliation remains the phase for uncertain remote state.
- Mission Overall State uses Ready, Starting, Running, Degraded, Stopping, Finalizing, Completed, Completed with Warning, and Failed. Remove Partial Failed from the external contract and map its active one-sided-failure meaning to Degraded.
- Aggregation follows lifecycle intent, not a loose set of active flags:
  - Ready: no selected child has started and the mission has no failure.
  - Starting: at least one selected child is starting and no child has entered a one-sided failure.
  - Running: all selected children required for the mission are actively recording without a current child fault.
  - Degraded: the mission is not terminal and one child is failed, offline, resume-expired, or uncertain while the other child remains active or can still produce a result.
  - Stopping: Stop All or an individual stop has been requested and at least one selected child is actively stopping or its stop result is still uncertain.
  - Finalizing: sampling has stopped, but file finalization, automatic upload, manual upload, or Upload Pending remains. Upload Pending cannot become Completed with Warning.
  - Completed: all selected services are terminal and every required artifact is Ready or Uploaded.
  - Completed with Warning: all selected services are terminal, no process remains uncertain, no finalization or upload is pending, one child completed successfully, and the other child permanently failed or is incomplete. The failed child may still expose a Partial GPS Result without becoming a successful child.
  - Failed: all selected children are terminal failures and no usable mission artifact remains.
- The frontend mission badge is driven directly by Mission Overall State. It adds child-derived reason text rather than creating combinatorial overall states, for example `DEGRADED · GPS FAILED — NOISE RECORDING`, `DEGRADED · NOISE OFFLINE — GPS RECORDING`, `COMPLETED · GPS FAILED`, or `COMPLETED · NOISE FAILED`.
- Backend and frontend state types must be updated together. Unknown response values must degrade safely in the UI rather than being summarized as Ready.

### WF2 — Device Health

- Device Health is a current, mission-independent projection. It must not mutate a terminal or historical Mission Child State when a device is unplugged or later reconnects.
- AP3 health answers whether capture can start using a lightweight ADB device check and forwarding readiness check. GPS accuracy, satellite count, and detailed diagnostics are not part of the initial health contract.
- RasPi health answers whether USRP capture can start using a bounded SSH connection and a lightweight service-state probe. Journal history, full service status, and bulk logs are diagnostics and must not run in heartbeat polling.
- When healthy and idle, check each device approximately every 10 seconds. When offline, retry using 5, 10, 20, then 30 seconds, capped at 30 seconds until recovery.
- Device Health includes enough timestamps and error context for the frontend to distinguish fresh Ready, Offline, and Unknown results. A stale or timed-out probe must not be reported as Ready.
- The frontend updates Device Health without page reload and names AP3 or Raspberry Pi in unavailable-start messages.

### WF3 — Bound start

- Bound Start performs AP3 and RasPi／USRP preflight before creating a mission. If either preflight fails, no Bound Mission is created and neither child starts.
- A preflight rejection returns structured per-device errors so the UI can name every unavailable device rather than showing only a generic capture-unavailable message.
- After both preflights pass, create exactly one mission and assign its `mission_id` to the mission and both children before either launch begins.
- Child launches may proceed independently after mission creation. A post-creation launch failure is recorded on that child, the successful sibling remains active, and the mission becomes Degraded. Do not roll back the successful launch.
- Individual AP3 or USRP capture remains available while Bind is disabled, subject to the relevant Device Health and conflict rules.
- Bind and Test／USRP mode controls cannot change while either child is active or while a stop/finalization operation is unresolved.

### WF4 — Runtime monitoring and recovery

- Active frontend status polling is single-flight: wait for the current status response to settle, then wait approximately two seconds before sending the next request. Aborting a stale request is allowed, but overlapping requests are not.
- Runtime AP3 monitoring must combine local recorder-process ownership, AP3 connection readiness, and last valid GPS sample freshness. A live local process without fresh GPS must not be presented as healthy recording.
- Runtime RasPi monitoring uses lightweight health plus remote mission-state reconciliation. On SSH loss, set Connection to Offline and preserve Presumed running when the remote service cannot be proven stopped. The mission becomes Degraded and AP3 continues.
- When SSH recovers, read the remote state for the same `mission_id` and reconcile USRP. Return the mission to Running only when remote recording is positively confirmed. Never create a replacement mission during reconciliation.
- AP3 Capture Resume is automatic. It applies only while the same Bound Mission is active and has not entered Stop, Finalizing, or a terminal state.
- Resume eligibility is based on the time gap between the last parseable valid GPS row already persisted for the mission and the reconnection confirmation or first valid recovery sample. A gap of 300 seconds or less may resume; a larger gap is a Resume Timeout.
- Resume appends to the existing GPS file, preserves the header, does not duplicate it, does not truncate prior rows, does not synthesize the missing interval, and preserves the original `mission_id`.
- If the recorder process survived the outage, it must still enforce the same five-minute limit before accepting resumed writes. If the recorder process ended, a distinct resume path may relaunch it in append mode; ordinary Start must not guess that it is a resume.
- Persist the last sample time, disconnect time, and resume deadline in mission state so a backend restart does not erase the decision boundary. The GPS file's last parseable timestamp remains the authoritative evidence for already written data.
- A Resume Timeout ends AP3 participation in that mission. AP3 Health may later become Ready for the next mission, but the old child remains failed with a resume-timeout phase. Existing valid GPS rows are finalized and exposed as a Partial GPS Result.
- The frontend shows the resume timeout explicitly and, when present, states that a partial GPS file is available.

### WF5 — Stop and finalization

- Stop All starts AP3 and USRP stop attempts concurrently. The contract guarantees both are attempted, not exact stop-time synchronization.
- Stop is Best-Effort. An exception, timeout, or failure in one child cannot cancel or prevent the other child's stop and finalization.
- Persist that Stop All was requested so a page or backend restart does not restore the original Stop All action incorrectly.
- While a remote service may still be running, keep it Presumed running or in a stop-failed／reconciling state. Never mark the child Stopped or the mission Completed without evidence.
- Reuse each child's existing Stop control as the recovery control. When a stop is retryable, relabel it Retry Stop and invoke only that child's stop operation with the original `mission_id`.
- After the first Stop All attempt, disable Stop All. A successfully stopped child shows a disabled Stopped control; only failed children retain Retry Stop.
- USRP Retry Stop remains disabled while RasPi is Offline and explains that reconnection is required. It becomes available when RasPi health recovers. AP3 Retry Stop may remain available when the backend still owns or can safely reconcile the local recorder.
- There is no Force Complete or local-only Force Stop action. Unknown remote state must remain explicit until reconciled.
- Use one canonical GPS schema containing timestamp, latitude, longitude, altitude, and altitude mode. Creation, append, stop validation, upload, parsing, and tests must all consume the same schema definition rather than duplicating headers.
- AP3 finalization preserves valid rows after capture failure or Resume Timeout. A partial file can be Ready while the AP3 service outcome remains Failed, enabling Completed with Warning after the sibling finishes.

### WF6 — Upload engine

- After USRP stop successfully finalizes Noise, trigger one immediate automatic upload. This initial attempt is distinct from the three delayed retries.
- If the initial upload fails, keep File as Upload Pending and schedule automatic Retry 1/3 after 5 seconds, Retry 2/3 after 15 seconds, and Retry 3/3 after 30 seconds.
- Automatic retries are finite. After all three delayed retries fail, keep Upload Pending and expose Manual Retry. Do not convert the mission to Completed with Warning while upload remains retryable and pending.
- Persist upload retry mode, state, attempt number, maximum attempts, next-attempt timestamp, active-attempt start timestamp, and last error in mission state. A backend restart resumes a pending schedule without resetting completed attempts or duplicating an active job.
- Decouple the backend request from long-running remote upload execution. Trigger a bounded background upload job, persist its identity/progress, and reconcile its result through status monitoring.
- Waiting automatic retries display `自動重試 N/3 (X s)` with a one-second countdown derived from persisted server timestamps.
- Active automatic retries display `正在重試 N/3 (X s)` with a one-second elapsed counter.
- A failed intermediate attempt advances directly to the next waiting countdown without a transient timeout/failure label.
- Only after the third retry fails does the frontend display `自動重試已用盡`.
- Manual Retry is always retained after automatic exhaustion. During execution it displays `手動重試 (X s)`. It does not reset or alter the automatic retry count, and a failed manual attempt remains manually retryable.
- Successful upload changes the USRP file to Uploaded, clears pending retry state and relevant upload errors, and allows aggregation to reach Completed when the AP3 result is also terminal and usable.

### Persistence, concurrency, and API behavior

- The existing mission state file remains the persistent source of truth. All new resume, stop, and upload-retry metadata must survive backend restarts.
- Continue using the coordinator's established locking discipline and atomic replace writes. Status polling, Stop All, Retry Stop, AP3 Resume, upload acknowledgement, and retry scheduling must not write the same mission state concurrently without coordination.
- Route handlers remain thin: validate input, call the coordinator or hardware adapter, and format the response. Blocking ADB, SSH, subprocess, and HTTP work must be bounded by timeouts and executed without blocking the async server loop.
- Status responses expose Device Health separately from the selected or current Mission Child States while preserving the mission's historical truth.
- Start, Stop, Retry Stop, Resume, Upload Retry, and status operations return the resulting state contract or a structured error. Hardware/service unavailability must not prevent API startup.
- Preserve the established security rules for validated mission identifiers, safe filenames, upload size/hash validation, safe shell quoting, and credentials sourced only from environment configuration.

## Testing Decisions

- Tests assert externally observable state transitions, persisted results, API contracts, rendered text, and enabled actions. Avoid tests coupled only to private helper calls or incidental command ordering.
- The primary backend seam is the Capture Coordinator's public operations plus the persisted mission state they produce. This is the highest existing seam that covers aggregation, Bound Start, runtime recovery, Stop, finalization, and upload orchestration.
- State aggregation coverage includes every canonical outcome and priority boundary: Ready, Starting, Running, one-sided Degraded, Stopping, Finalizing, Completed, Completed with Warning for GPS failure, Completed with Warning for Noise failure, and Failed with no usable result.
- Bound Start coverage includes both preflights succeeding, each preflight failing before mission creation, each launch failing after mission creation, one shared mission identifier, and proof that the healthy child is not rolled back.
- Device Health adapter tests mock AP3 online/offline and SSH success/failure, verify lightweight probes and offline backoff, and prove that health changes do not mutate terminal mission results.
- AP3 recorder tests independently cover canonical schema creation, append without truncation or duplicate header, 299/300-second resume acceptance, over-300-second rejection, malformed-header rejection, freshness loss while the process remains alive, Partial GPS Result preservation, and backend-restart recovery from persisted metadata plus the last valid row.
- USRP adapter tests use fake SSH and remote mission state for Ready/Offline, Presumed running, recording reconciliation, stop timeout, successful Retry Stop, finalization, upload trigger, upload success, HTTP failure, SSH failure, and remote timeout.
- Stop tests prove both child attempts begin without one waiting for the other's completion, one exception does not prevent the sibling attempt, Stop All becomes consumed, only the failed child can Retry Stop, and an uncertain remote child cannot produce Completed.
- Upload tests use a controllable clock and fake background jobs. They cover the immediate attempt, 5/15/30-second schedules, exact attempt numbering, no overlapping jobs, direct transition between failed attempts and the next countdown, exhaustion, Manual Retry, successful manual recovery, and restart restoration without resetting attempts.
- API tests validate input, response shape, explicit unavailable-device errors, conflict and unavailable status codes, mission identifier preservation, and delegation to the coordinator. They do not duplicate coordinator transition tests.
- Frontend tests use the telemetry component as the seam. They cover mission badge mapping, GPS／Noise-specific reason text, Device Health independent from child state, Bound Start eligibility, mode locking, Stop／Retry Stop／Stopped controls, Resume Timeout and Partial GPS Result text, Upload Pending, retry countdown, elapsed-time labels, exhaustion, Manual Retry, and accessible error announcements.
- Frontend polling tests use fake timers and deferred responses to prove single-flight behavior: no second request starts until the current request settles and the post-response interval elapses.
- Reuse the repository's existing fake process, fake backend, temporary Capture Store, API coordinator mock, Vitest fake timers, and telemetry rendering patterns as prior art.
- Run the affected backend suite after each workflow, the affected frontend suite for UI or polling changes, and the frontend production build after frontend work.
- Hardware acceptance is a separate final layer and is not required for ordinary automated tests. It includes AP3 unplug/replug within and beyond five minutes, RasPi network loss/recovery, one-sided launch and stop failures, successful Stop All, Noise upload retry/exhaustion/manual recovery, and an end-to-end Bound Mission artifact check.

## Out of Scope

- Row-by-row timestamp alignment between GPS and Noise.
- A requirement that every GPS row has a corresponding Noise row or vice versa.
- Exact synchronized AP3 and USRP Start or Stop timing.
- Automatically stopping the healthy child when its sibling fails.
- Rolling back a successful child after a one-sided Bound Start failure.
- Automatically creating a new mission after AP3 Resume Timeout.
- Synthesizing, interpolating, or backfilling GPS data during an AP3 outage.
- A Force Complete or unsafe local-only force-stop operation for an uncertain remote service.
- Infinite automatic upload retry or resetting automatic retry history through Manual Retry.
- AP3 satellite count, GPS accuracy, or other deep diagnostics in the first Device Health contract.
- Heavy journal or full service-log retrieval as part of heartbeat monitoring.
- Redesigning the entire capture subsystem when the existing mission／child model can evolve.
- Making hardware-dependent tests mandatory in normal automated test runs.

## Further Notes

- The current system already contains the dual-child mission model, shared `mission_id` support, preflight behavior, child-isolated launch failure handling, manual upload retry, atomic mission-state writes, and substantial backend/frontend test scaffolding. Work should evolve these seams instead of replacing them.
- Known gaps include the legacy Partial Failed overall value, Active／Ready frontend summary, overlapping interval polling, Device Health mixed with mission status, incomplete AP3 data-freshness detection, resume relaunch truncating GPS unless separated from ordinary launch, inconsistent GPS schema declarations, sequential Stop All behavior, and upload execution tied to bounded remote commands.
- The Bound Mission independent-lifecycle decision is recorded in ADR 0002 and is normative for all workflows in this spec.
- WF1–WF3 constitute the first release. Do not start runtime recovery work until their state, health, start, UI, and integration acceptance tests pass together.
- After this spec is accepted, use `to-tickets` to produce tracer-bullet issues with explicit blocking edges. Tickets generated from this spec are already agent-ready and must not be sent through triage.

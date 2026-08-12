# 10 — 建立背景 Noise Upload 與 Manual Retry

**What to build:** USRP 成功 finalize Noise 後立即觸發一次背景自動上傳，不讓 API request 綁住遠端 SSH／HTTP 時間；失敗時保留 Upload Pending 與可操作的 Manual Retry，直到成功上傳後才允許 Mission 完成。

**Blocked by:** 09 — 覆用 Child Stop 提供 Retry Stop.

**Status:** ready-for-agent

- [ ] USRP finalize 成功後觸發一次 immediate automatic upload，且不需操作人員額外按鈕。
- [ ] Upload 使用 bounded background job；觸發 request 不等待完整遠端 SSH command 與 HTTP upload 才返回。
- [ ] 任務狀態持久化足以辨識 upload job 的 waiting／running／success／failure 與最後錯誤，status 可 reconcile 結果。
- [ ] Immediate upload 成功時 USRP File 進入 Uploaded，清除 upload error，並在 AP3 outcome 允許時聚合為 Completed。
- [ ] Immediate upload 失敗或 timeout 時 USRP File 保持 Upload Pending，Mission 保持 Finalizing，不得 Completed with Warning。
- [ ] Upload Pending 提供 Manual Retry；執行中前端顯示 `手動重試 (X s)` 並每秒更新 elapsed time。
- [ ] Manual Retry 成功後進入 Uploaded；失敗後仍 Upload Pending 且可再次手動操作。
- [ ] Upload acknowledgement、status reconciliation、stop 與 manual retry 併發時不破壞任務持久化資料。
- [ ] 後端重啟後可辨認先前 background job 的持久化狀態，不會把未知執行誤報成功。
- [ ] Adapter、Coordinator、API 與 Frontend tests 涵蓋 immediate success、HTTP failure、SSH failure、timeout、Manual Retry success／failure 與 elapsed label。

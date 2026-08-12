# Bound missions keep independent child lifecycles

AP3 與 USRP 在綁定任務中共用同一個 `mission_id`，但各自維護 Connection、Service、File 與 Error 狀態。單邊啟動、執行或停止失敗時，另一邊不回滾也不連帶停止，因為綁定代表共同歸屬於一次量測，而不是兩個裝置具有相互依賴的生命週期。

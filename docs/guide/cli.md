# 命令列

TypeScript 版的指令是 `harness`，Python 版是 `pyharness`，共用的指令與選項相同。

```text
harness new <資料夾> [--lang python|ts]   建立新專案
harness chat                              開始聊天
harness run "<訊息>"                      執行一次後結束（適合排程與腳本）
harness web                               開啟網頁版

chat 與 run 共用的選項：
  -p, --project <資料夾>     專案位置（預設為目前資料夾）
  -a, --agent <名稱>         使用哪個 agent
  -m, --model <名稱>         覆寫模型
  -c, --continue             接續最新的對話
  -r, --resume <ID>          接續指定的對話
      --bypass               所有工具都不詢問直接執行

web 的選項：
  -p, --project <資料夾>     專案位置（預設為目前資料夾）
      --port <埠號>          預設 4321
      --host <位址>          預設 127.0.0.1（只有本機能連）
```

聊天時按 Ctrl-C 會中斷目前這一輪，不會結束整個聊天。

## Python 版多出的指令

```text
pyharness run -c /compact    壓縮最新的對話（聊天時直接輸入 /compact）
pyharness memory             查看長期記憶（forget <識別碼> / clear）
pyharness knowledge ["查詢"]  檢查知識庫索引，或試著搜尋
                             （-l hr,sales 模擬受限的 agent，
                             -b hr,it 只搜尋這幾個知識庫）
pyharness ontology           載入 ontology 並列出每個綁定（log 動作紀錄、
                             candidates 回報的候選概念、--reload 全部重載）
pyharness sandbox            檢查沙盒（Docker）能不能正常執行程式
pyharness user add <名稱>     新增網頁版的帳號，印出產生的密碼
                             （--name 顯示名稱、--admin 設為管理者）
pyharness user list          列出帳號
pyharness user passwd <名稱>  重設密碼（原本的登入全部失效）
pyharness user disable <名稱> 停用帳號（enable 重新啟用）
pyharness data               網頁版的資料庫版本與快照
pyharness data backup        現在拍一份快照（資料庫與設定檔）
pyharness data restore <名稱> 換回某一份快照（先停止網頁版）
```

`pyharness user` 管理[網頁版的帳號](/guide/web#帳號與成員)，存在專案的 `.harness/harness.db`，`-p` 指定專案資料夾。

`pyharness data` 管理網頁版的資料版本：`pyharness web` 啟動時發現程式換了版本，會先把資料庫與設定檔快照到 `.harness/backups/`，再自動升級資料庫，所以更新不需要手動備份（見[更新版本](/guide/deploy#更新版本)）。

`pyharness web` 另外有這些選項：

| 選項 | 用途 |
|---|---|
| `--allowed-host <主機名稱>` | 只接受用這個網址連線，可以重複（見[部署到伺服器](/advanced/server)） |
| `--trusted-proxy <IP或網段>` | 信任的反向代理，可以重複，或用環境變數 `HARNESS_TRUSTED_PROXIES`（逗號分隔）；只有來自這些位址的請求才採信 `X-Forwarded-For` 與 `X-Forwarded-Proto`（見[部署到伺服器](/advanced/server)） |
| `--max-upload-mb <MB>` | 單一上傳檔案的上限，預設 50 |

在空的資料夾執行 `pyharness web` 時，會自動建立可以直接使用的助手（見[網頁版](/guide/web#自動建立助手)）。

相關說明：[對話壓縮](/advanced/compaction)、[長期記憶](/advanced/memory)、[知識庫](/advanced/knowledge)、[Ontology](/advanced/ontology)、[在沙盒裡執行程式](/advanced/sandbox)。

## 在排程裡使用

`run` 執行一次就結束，適合放進 cron 或 CI。無人值守時沒有人可以回答權限詢問，可以把權限模式設成 `dontAsk`（需要同意的工具一律拒絕），或確定安全時加上 `--bypass`。見[權限](/guide/permissions)。

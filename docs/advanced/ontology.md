# Ontology（業務物件） <span class="badge-py">Python 版</span>

知識庫讓 agent 從文件裡找答案；ontology 讓 agent 查**業務物件**：合約、
供應商、案件、關卡這些有識別碼、有屬性、彼此有關係的資料。agent 不用
自己從文件或檔案裡拼湊「這份合約的供應商是誰」「現在有幾件高風險案件」，
而是用五個語意工具查詢，答案來自你定義好、資料來源綁好的物件。

- **定義檔放在專案裡。** `ontology/` 底下的 YAML 寫型別、屬性、關係、
  動作、指標與詞彙，可以進版控、審查。
- **資料不經過 LLM。** 物件來自 JSON、YAML、CSV 檔案、知識庫的條文，或
  自己寫的 Python 函式，照綁定規則轉換；每一筆都記著出處與有效期間。
- **只有五個工具。** 查物件、走關係、搜對應的文件、查指標、執行動作；
  動作是唯一的寫入方式，每次都要使用者核准並填理由，寫進動作紀錄。
- **權限套到每一筆。** 型別與屬性可以設機密等級，超過 agent 等級的屬性
  會遮起來；型別與動作可以限定群組。

完整的範例在 [`examples/ontology_demo`](https://github.com/xian-ai-1057/AgentHarness/tree/main/examples/ontology_demo)
（虛構的合約管理：單位、人員、供應商、系統、合約、委外規章）：

```bash
pyharness ontology check -p examples/ontology_demo   # 載入並列出每個綁定
pyharness chat -p examples/ontology_demo             # 和 contracts agent 聊
```

## 啟用

專案有 `ontology/` 資料夾就會載入，再在 agent 的 frontmatter 寫要用哪些
模組：

```markdown
---
name: contracts
description: 合約管理助手
ontology:
  modules: [contracts]          # 這些模組（含它們 imports 的模組）；true 表示全部
  maxClassification: internal   # 這個 agent 能讀的最高機密等級（可省略）
---
你是合約管理助手。
```

設定了 `ontology` 的 agent 會拿到五個工具，指示後面自動接上這些模組的
型別、關係、動作與詞彙摘要，模型不用猜有哪些欄位。其他 agent 也可以在
`tools` 列出 `ontology` 這個 toolset，但不會有定義摘要。

`harness.yaml`（整個區塊可省略）：

```yaml
ontology:
  path: ontology               # 定義檔資料夾（預設）
  maxClassification: internal  # agent 沒設定時能讀的最高等級（預設不限）
  levels:                      # 自訂機密等級，由低到高（預設如下）
    - { id: public, label: 公開 }
    - { id: internal, label: 內部使用 }
    - { id: confidential, label: 機密 }
    - { id: restricted, label: 極機密 }
```

寫 `ontology: false` 可以停用。物件存在專案的 `.harness/ontology.db`
（SQLite），每次使用前檢查來源有沒有變，只重新載入變動的綁定。

## 定義檔

一個 YAML 檔是一個模組。模組可以 `imports` 其他模組（例如共用的人員、
單位），`documents` 列出這個模組的文件放在哪些知識庫：

```yaml
module: contracts
label: 合約管理
description: 供應商提供哪些系統、簽了哪些合約，以及規章怎麼規定。
imports: [core]
documents: [policies]          # search_documents 搜尋的知識庫

types:
  contract:
    label: 合約
    key: 合約編號               # 識別碼是什麼（寫給模型看）
    display: "{title}"         # 顯示名稱的樣板
    classification: internal   # 型別的機密等級（預設 internal）
    groups: [採購部]            # 只有這些群組看得到（可省略）
    properties:
      title: { label: 合約名稱, required: true }
      status: { label: 狀態, enum: [生效中, 已到期, 洽談中] }
      end_date: { label: 到期日, type: date }
      amount: { label: 金額（萬元）, type: number, classification: confidential }

relations:
  with_vendor:
    label: 簽約對象
    from: contract
    to: vendor
    inverse: contracts         # 反方向的名稱，get_related 可以直接用
    inverseLabel: 合約

glossary:
  - term: 關鍵供應商
    definition: 提供重要性為「高」的系統，或停止服務會影響營運的供應商。
    aliases: [重要供應商]       # find_entity 查詢時也會展開
    owner: 採購部
```

屬性的 `type` 可以是 `string`（預設）、`integer`、`number`、`boolean`、
`date`、`array`、`object`。識別碼（型別、屬性、關係的名稱）只能用小寫
英數字與底線；YAML 會把 `no`、`yes` 當成布林值，不要拿來當名稱。

定義檔有錯時，載入會一次列出全部的錯誤（引用不存在的型別、關係、知識庫
或等級等），`pyharness ontology check` 也會。

## 資料綁定

`bindings` 把真實資料對到物件，有三種來源。

**檔案**（JSON、YAML、CSV）：

```yaml
bindings:
  - name: contracts
    type: contract
    file: data/contracts.yaml   # 相對於專案根目錄，可以寫 ${環境變數}
    records: contracts          # 清單在檔案裡的位置（用 . 分隔）
    id: contract_no             # 識別碼欄位，或樣板 "{unit}-{no}"
    properties: { title: title, status: status, end_date: end, amount: amount }
    links: { with_vendor: vendor, covers: systems }   # 欄位裡是對方的識別碼
    validFrom: start            # 生效日欄位（可省略）
    validTo: end_at             # 失效日欄位，當天起不再有效（可省略）
```

欄位規則可以寫巢狀欄位（`評等.等級`）、樣板（`{unit}-{no}`）或固定值
（`=是`）。關係欄位可以是清單，或用逗號、頓號分開；`~關係` 表示反方向。

**知識庫**：每一條條文變成一個物件，屬性有文件代碼、條號、章節、頁碼與
條文內容，物件也記著對應的片段，`search_documents` 用它限定搜尋範圍。
知識庫要設定 `chunking: regulation`（見[依條文切片](/advanced/knowledge#依條文切片)）。

```yaml
  - name: policy_articles
    from: knowledge
    base: policies
    type: policy_article
    docId: "^([A-Z]+-[0-9]+)_"   # 從檔名取出文件代碼（可省略，預設用檔名）
    references: refers_to        # 條文提到「第 N 條」時連到同文件的那一條
    document: in_policy          # 每一條連到文件代碼相同的物件（例如規章本身）
```

**Python**：處理函式回傳整理好的紀錄，適合要計算或要讀其他系統的資料：

```yaml
  - name: platform
    run: loaders.py:load         # ontology/ 底下的檔案:函式
    watch: [data/export.json]    # 這些檔案改了才重新載入
```

```python
def load(ctx):                   # ctx.root 專案根目錄，ctx.warn() 記警告
    return [
        {"type": "vendor", "id": "V01", "properties": {"name": "甲公司"},
         "links": {"supplies": ["SYS-CRM"]}, "validFrom": "2025-01-01"},
    ]
```

一筆紀錄可以帶自己的 `type`，所以一個函式可以產生好幾種物件。沒寫
`watch` 時每次啟動服務重新載入一次。

## 五個工具

| 工具 | 做什麼 |
| --- | --- |
| `find_entity` | 查物件：給型別與關鍵字或屬性條件。只找到一筆時顯示完整內容（屬性、分級、有效期間、出處、有哪些關係）；什麼都不給時列出可以查的型別。 |
| `get_related` | 從一個物件沿關係走，例如 `["with_vendor", "supplies"]` 是「這份合約的供應商提供哪些系統」，最多 4 步。 |
| `search_documents` | 搜尋文件段落；指定物件時只搜那個物件（與沿著 `path` 走到的物件）對應的段落，例如某份合約適用的條文。出處格式和 `search_knowledge` 一樣，網頁版的 `[1]` 可以點。 |
| `get_metric` | 查定義好的指標，大家算出來都一樣。 |
| `run_action` | 執行定義好的動作，見下一節。 |

查詢都可以給 `as_of`（YYYY-MM-DD）查某一天有效的資料。

### 指標

```yaml
metrics:
  contracts_by_status:
    label: 各狀態合約數
    count: contract              # 數哪個型別
    where: { status: 生效中 }     # 條件（可省略）
    groupBy: status              # 分組（可省略）
    unit: 件
  expiring_contracts:
    label: 即將到期的合約
    run: metrics.py:expiring_contracts
    params:
      days: { type: integer, description: 幾天內到期（預設 90） }
```

Python 指標收到 `ctx.view`（已經套用權限與日期，`objects()`、`get()`、
`related()`），回傳數字、文字或對照表。

## 動作

動作是 agent 唯一的寫入方式：

```yaml
actions:
  request_renewal:
    label: 申請續約
    target: contract             # 動作的對象型別（target_id 必填）
    create: renewal_request      # 在 ontology 裡建立這種物件，參數就是屬性
    check: actions.py:can_renew  # 核准前的檢查（可省略）
    params:
      months: { type: integer, required: true, minimum: 1, maximum: 36 }
    effects: 在 ontology 裡建立一筆續約申請
  flag_vendor_risk:
    label: 標記供應商風險
    target: vendor
    run: actions.py:flag_vendor_risk   # 或寫處理函式（和 create 擇一）
    params:
      level: { required: true, enum: [高, 中, 低] }
```

```python
def can_renew(ctx, months, note=""):
    """回傳說明表示不能執行（不會請使用者核准）；None 表示可以。"""
    if ctx.target.props.get("status") == "已到期":
        return f"{ctx.target.label} 已到期，要重新簽約"

def flag_vendor_risk(ctx, level, finding):
    path = ctx.run.workdir / "風險標記" / f"{ctx.target.id}.md"
    ...                          # ctx.record(型別, 識別碼, 屬性) 可以在 ontology 記一筆物件
    return harness.PRODUCED_MARKER + f"風險標記/{ctx.target.id}.md"
```

- **每次都要核准。** `run_action` 不受權限模式、`allow` 規則與 hooks 的
  allow 影響，網頁版的核准卡片只有「允許這一次」與「拒絕」，並顯示動作、
  對象、參數、理由與會做什麼。`dontAsk` 模式下一律拒絕。
- **先檢查再問。** 動作不存在、理由沒填、參數不對、對象找不到，或
  `check` 回傳了說明，都會直接告訴模型，不會請使用者核准。
- **一定有紀錄。** 每次執行（含被拒絕、失敗）都寫進動作紀錄，只能新增
  不能修改；網頁版的稽核紀錄也會記一筆「執行 Ontology 動作」。
  `pyharness ontology log` 可以看最近的紀錄。
- **回報缺少的概念。** 每個 ontology 都有內建的 `report_missing_concept`：
  使用者提到定義裡沒有的概念時，agent 可以回報，進候選清單給定義檔的
  負責人審查（`pyharness ontology candidates`）。

## 權限

- **機密等級。** 型別與屬性的 `classification` 和 agent 的
  `maxClassification` 比較：型別超過等級的看不到，屬性超過等級的值會顯示
  成「（機密，這個助手不能讀取）」。
- **群組。** 型別與動作的 `groups` 列出群組 id 或名稱，網頁版只有這些
  群組的成員能查看或執行（管理者不受限制）。
- **知識庫。** `search_documents` 只搜尋這個人能搜尋的知識庫，和
  `search_knowledge` 一樣。
- **工具組。** 網頁版的群組要開放 `ontology` 工具組，成員才能用這五個
  工具。

## 命令列

```text
pyharness ontology [check]     載入並列出每個綁定的物件數、關係數與警告
pyharness ontology log         最近的動作紀錄
pyharness ontology candidates  回報的候選概念
  -p <資料夾>   專案位置
  --reload     不管有沒有變動，全部重新載入
```

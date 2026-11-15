# 知識庫（RAG） <span class="badge-py">Python 版</span>

讓 agent 從文件裡找答案並附上出處。把文件放進 `knowledge/` 資料夾，
再在 agent 設定 `knowledge: true`：

```
knowledge/
├── hr/
│   └── leave.md
├── product.md
└── manual.pdf        需要 pypdf（安裝時加上 [pdf]，見下方）
```

```markdown
---
name: faq
knowledge: true       # 這個 agent 可以用 search_knowledge 搜尋知識庫
---
你是公司的 FAQ 助手。回答前先搜尋知識庫，並註明出處。
```

agent 會得到 `search_knowledge` 工具，搜尋結果附上來源檔案與所在標題
（PDF 則是頁碼），例如 `[1] 來源：hr/leave.md › 請假規定 › 特休`。
同一輪回答裡搜尋好幾次時，編號會接續下去（第一次 1～5、第二次 6～10），
回答裡的 `[n]` 不會同時指到兩次搜尋的不同片段；工具說明也請模型直接
寫這個編號，不要改成 `[A1]` 或檔名。

文件多了以後，可以依主題或部門分成[好幾個知識庫](#分成好幾個知識庫)，
各自有自己的資料夾、檢索設定與維護者。

- **檢索方式。** 有三種，用 `searchMode` 選（見[檢索方式](#檢索方式)）：
  - **關鍵字**（`keyword`）：精確比對，只看查詢的字詞有沒有出現、出現
    幾次，不需要任何模型。適合查表單編號、專有名詞。
  - **演算法**（`bm25`，沒有 embedding 模型時的預設）：BM25 演算法依字詞
    的稀有度與片段長度排序，不需要任何模型。中文也能用（以單字與相鄰
    兩字比對，不用另外斷詞）。
  - **BM25 + 語意**（`hybrid`，設定 `embeddingModel` 時的預設）：再加上
    embedding 模型的語意檢索，兩者的排名合併（hybrid search），同義詞、
    換句話說也找得到。
- **檔案改了會自動更新。** 每次搜尋前會檢查檔案有沒有變動，有就重建
  索引。embedding 存在內建的向量資料庫，沒變的片段不會重新計算（見
  [向量資料庫](#向量資料庫)）。
- **過濾不相關的結果與重新排序。** 可以設定相似度門檻，把與問題不夠
  相似的片段丟掉；也可以用 reranker 重新評估前幾名的相關度（見
  [相似度門檻與 reranker](#相似度門檻與-reranker)）。
- **切片。** 依段落切成約 `chunkSize` 字的片段，不會從段落中間切開。
  法規、內規類的文件可以改成一條一片（見[依條文切片](#依條文切片)）。
- 支援 `.md`、`.txt`、`.pdf`、`.docx`、`.pptx`、`.xlsx`；其他格式會略過，
  用 `pyharness knowledge` 可以看到哪些檔案被略過。Word、PowerPoint、
  Excel 用 Python 內建的套件讀取，不需要另外安裝；讀取 PDF 需要 pypdf：

  ```bash
  pip install "agent-harness[pdf] @ git+https://github.com/xian-ai-1057/AgentHarness.git#subdirectory=python"
  ```

  各格式讀出的內容與出處見[文件解析](#文件解析)，也可以換成自己的解析器。

`harness.yaml`（整個區塊可省略，有 `knowledge/` 資料夾就會啟用）：

```yaml
knowledge:
  path: knowledge                              # 預設
  searchMode: hybrid            # keyword、bm25 或 hybrid；省略時依有沒有 embeddingModel
  embeddingModel: openai/text-embedding-3-small  # 省略時只用 BM25
  chunkSize: 800                               # 預設
  chunking: paragraph           # 預設；regulation 是依條文切片
  minSimilarity: 0.3            # 選用，語意相似度門檻（需要 embeddingModel）
  reranker: cohere/rerank-v3.5  # 選用，重新排序用的模型
  rerankCandidates: 20          # 交給 reranker 的候選數，預設 20
  minRerankScore: 0.2           # 選用，rerank 分數門檻（需要 reranker）
```

`embeddingModel` 與 `reranker` 是 litellm 的模型名稱（上面的例子是直接
連供應商的寫法）。有設定 `HARNESS_BASE_URL` 時會改連那個端點，和聊天
模型一樣，名稱要寫端點上的名稱；用 LiteLLM Proxy 時就是它設定檔裡的
`model_name`（見[模型設定](/guide/model)）。reranker 走 Proxy 的
`/v1/rerank`。

## 檢索方式

`searchMode` 決定怎麼找片段：

| 值 | 網頁版的選項 | 做法 | 需要模型 |
|---|---|---|---|
| `keyword` | 關鍵字（精確比對） | 片段裡原樣出現查詢字詞（以空白分開的每一段）的排前面，再依命中幾個詞、出現幾次排序；中文只用相鄰兩字比對，單一個字不算 | 不用 |
| `bm25` | 演算法（BM25） | BM25：越少見的詞分數越高，並依片段長度調整 | 不用 |
| `hybrid` | 選一個 embedding 模型 | BM25 加上語意檢索，排名合併 | `embeddingModel` |

沒寫 `searchMode` 時，有 `embeddingModel` 就是 `hybrid`，沒有就是 `bm25`。
選了 `keyword` 或 `bm25` 時不會呼叫 embedding 模型，`minSimilarity` 也不
生效。其他知識庫沒寫時沿用 `knowledge` 區塊的 `searchMode`；自己寫了
`embeddingModel` 卻沒寫 `searchMode` 時，表示要用那個模型（`hybrid`），
不沿用預設知識庫的關鍵字或 BM25。

網頁版「管理平台 → 知識庫」的「Embedding 模型」與「Reranker」是下拉選單：
「Embedding 模型」依序是「關鍵字（精確比對）」「演算法（BM25）」、模型
連線上的 embedding 模型、「其他（自行輸入）」，其他知識庫最後還有
「沿用預設知識庫」；「Reranker」是「不重新排序」（其他知識庫是「沿用
預設知識庫」）、模型連線上的 rerank 模型與「其他（自行輸入）」。模型
清單的來源（`GET /api/knowledge/models`）：

- 連 LiteLLM Proxy 時讀它的 `/model/info`，依 `model_info.mode` 分出
  `embedding` 與 `rerank` 模型（只列這把金鑰能用的）。自架模型 LiteLLM
  不認得時，在 Proxy 設定檔的 `model_info` 寫上 `mode: embedding` 或
  `mode: rerank`，或取名時帶 embed、rerank 等字樣。
- 其他 OpenAI 相容端點（例如 vLLM）沒有 `/model/info`，改用 `/models` 的
  名稱判斷：名稱有 rerank 的是 rerank 模型；有 embed、bge、e5、gte、
  nomic 等字樣的是 embedding 模型。
- 直接連 OpenAI 時列出 text-embedding 系列；其他供應商沒有清單，選
  「其他」自行輸入。

## 分成好幾個知識庫

::: tip 使用者自己的知識庫
網頁版的使用者也可以在側欄「知識庫」建立只有自己能用的知識庫，上傳自己的文件，不必請管理者改 `harness.yaml`，見[網頁版的「我的知識庫」](/guide/web#我的知識庫)。這一節說的是管理者設定、給大家用的公司知識庫。
:::

一個知識庫放所有文件，管理上容易混在一起：誰可以更新哪些文件、哪些
人可以搜尋哪些內容都不好分。可以在 `harness.yaml` 的 `knowledgeBases`
區塊依主題或部門分成好幾個知識庫：

```yaml
knowledge:                       # 預設知識庫（識別碼 default），可省略
  embeddingModel: openai/text-embedding-3-small
  reranker: cohere/rerank-v3.5

knowledgeBases:
  hr:                            # 識別碼：小寫英文、數字、- 與 _
    name: 人資規章
    description: 請假、出勤、薪資與福利
    # path: knowledge/hr         # 預設是 knowledge/<識別碼>
  it:
    name: IT 支援
    description: 帳號、VPN、設備申請
    chunkSize: 500               # 可以有自己的檢索設定
```

```
knowledge/
├── faq.md            預設知識庫
├── hr/               知識庫 hr
│   ├── labels.yaml   每個知識庫各自的標籤設定
│   └── 請假規定.docx
└── it/               知識庫 it
    └── VPN 設定.pdf
```

- **每個知識庫是獨立的。** 有自己的名稱、說明、資料夾與檢索設定
  （`searchMode`、`embeddingModel`、`chunkSize`、`chunking`、`reranker`、
  `rerankCandidates`、`minSimilarity`、`minRerankScore`）；沒寫的檢索設定沿用 `knowledge`
  區塊的。
- **原本的 `knowledge/` 就是預設知識庫**（識別碼 `default`），舊的設定
  不用改。其他知識庫的資料夾放在 `knowledge/` 裡面時，預設知識庫不會
  重複讀它們。不要預設知識庫時寫 `knowledge: false`。
- **向量資料庫分開存。** 預設知識庫在 `.harness/knowledge/`，其他知識庫
  在 `.harness/knowledge/bases/<識別碼>/`。

agent 用 `knowledge` 欄位選擇要搜尋哪些知識庫：

```markdown
---
name: helpdesk
knowledge: [hr, it]   # 搜尋 hr 與 it 兩個知識庫
---
```

| 寫法 | 搜尋範圍 |
| --- | --- |
| `knowledge: true` | 預設知識庫（沒有預設知識庫時是全部） |
| `knowledge: [hr, it]` | 列出的知識庫 |
| `knowledge: {bases: [hr], labels: [manager], topK: 8}` | 指定知識庫，再加上標籤與筆數限制 |

**同時搜尋好幾個知識庫時，結果合併成一份排序。** 各知識庫的分數彼此
不能直接比較（切片、檢索方式不同），所以：每個知識庫都用同一個
reranker 時依 rerank 分數排序；否則依各自的名次輪流取（Reciprocal Rank
Fusion）。每筆結果的出處前面加上知識庫名稱，例如
`[1] 來源：人資規章 / 請假規定.docx › 特休`。工具說明也會列出每個
知識庫的名稱與說明，讓 agent 知道去哪裡找。

`pyharness knowledge` 會列出每個知識庫的檔案與片段數；試搜尋時可以用
`-b` 只搜尋某幾個知識庫：

```bash
pyharness knowledge -b hr,it "特休怎麼算"
```

用網頁版時，管理者可以直接在「管理平台 → 知識庫」新增知識庫、上傳
文件、調整設定與試搜尋，不必手動改 `harness.yaml`；每個知識庫還可以
指定維護者，讓部門自己更新文件。群組決定成員可以搜尋哪些知識庫，成員
在對話裡勾選這次要搜尋的知識庫（見[網頁版的知識庫](/guide/web#知識庫)）。

## 依條文切片

法規、自律規範與公司內規通常一條（或一點）講一件事。依段落與字數切片
時，一條可能被切成兩半或和下一條黏在一起，回答時就引不準是哪一條。
放法規類文件的知識庫可以設定 `chunking: regulation`：

```yaml
knowledgeBases:
  regs:
    name: 主管機關規範
    chunking: regulation
```

- **條文**：文件裡有 3 條以上依序出現的「第 N 條」（法律、法規命令、
  自律規範），每條一片，出處記成 `第二章 總則 › 第五條`。「第五條之一」
  也算一條；全形數字、中文數字都可以。
- **要點**：沒有條文、但有 3 點以上依序出現的「一、」「二、」（行政
  規則、公司內規的要點、辦法），每點一片，出處記成 `第五點`。
- **其他文件照舊依段落切。** 同一個知識庫裡混放會議紀錄、說明文件也
  沒關係。
- 條號必須不倒退、一次最多跳 5 條（要點必須剛好是下一點），內文提到
  「依第三條規定」不會被當成新的一條。要點常常每章從「一、」重新編號，
  遇到章節標題時點號會重新開始，出處記成 `第二章 風險管理 › 第一點`。
- 「附錄」「附件」「附表」「參考資料」這類標題會結束前面的章節，後面的
  內容記在它們底下，例如 `附錄 › 第四點`，不會被算進最後一章。
- 目錄頁（一頁有 3 行以上帶引導點「……」）、結尾是頁碼的標題，以及在
  3 頁以上重複出現的頁首頁尾（例如「附件 3-1」）不算章節標題。
- PDF 的出處會加上頁碼，例如 `第五條（第 3 頁）`。單一條文超過
  `chunkSize` 時先依「（一）」「（二）」這類款目、再依句號切成幾片，
  每片盡量從一個款目開頭，頁碼是那一片開始的那一頁。

網頁版在「管理平台 → 知識庫 → 設定」的「切片方式」選擇；改了之後會
重建這個知識庫的索引。

## 文件解析

讀文件與切片是分開的兩步：先由**解析器**把檔案讀成一段段文字（並記下
位置，例如頁碼），再依段落切成片段。內建的解析器：

| 副檔名 | 讀出的內容 | 出處 |
| --- | --- | --- |
| `.md`、`.markdown`、`.txt` | 全文，frontmatter 的 `labels` 當成標籤 | 所在標題 |
| `.pdf` | 每一頁的文字（需要 pypdf） | `第 3 頁` |
| `.docx` | 段落與表格，Word 的標題樣式轉成 Markdown 標題 | 所在標題 |
| `.pptx` | 每張投影片的文字 | `第 2 張投影片` |
| `.xlsx` | 每個工作表一段，每列一行、儲存格之間用直線隔開 | 工作表名稱 |

Office 檔案在伺服器上用 Python 內建的套件讀取，有大小限制（解壓縮後
單一部分 50 MB、每個工作表 2 萬列），壞掉或太大的檔案會被略過並列在
警告裡。

解析器可以替換或新增：它收到檔案路徑，回傳 `Section` 清單。例如改用
外部服務解析 PDF（含掃描檔 OCR），或加上 HTML：

```python
from harness.knowledge import Section

def parse_html(path):
    text = html_to_text(path.read_text(encoding="utf-8"))
    return [Section(text)]

def parse_pdf_with_ocr(path):
    pages = my_ocr_service(path)
    return [Section(page.text, location=f"第 {page.number} 頁") for page in pages]

project = harness.load_project(".")
for base in project.knowledge_bases.values():
    base.knowledge.parsers[".html"] = parse_html
    base.knowledge.parsers[".pdf"] = parse_pdf_with_ocr
```

讀不了的檔案丟出 `OSError`、`UnicodeDecodeError`、`ImportError` 或
`ValueError`，該檔案會被略過並記在警告裡，不會讓整個知識庫壞掉。

## 相似度門檻與 reranker

只靠排名的話，知識庫裡就算沒有答案，也一定會回傳「最接近」的幾段，
agent 可能拿不相關的內容硬湊答案。兩種設定可以擋掉這些結果：

- **`minSimilarity`**：語意相似度（餘弦，-1 到 1）低於門檻的片段不回傳，
  關鍵字找到的片段也一樣要過門檻。需要設定 `embeddingModel`。
- **`reranker`**：先用關鍵字與語意檢索取出前 `rerankCandidates` 名，
  再交給 rerank 模型逐段判斷與問題的相關度、重新排序，排名比單純的
  向量相似度準確。可以搭配 **`minRerankScore`** 丟掉分數太低的片段。
  litellm 支援的 rerank 服務都能用（Cohere、Voyage、Jina、Together、
  自架的 Infinity / vLLM 等），例如 `cohere/rerank-v3.5`
  （環境變數 `COHERE_API_KEY`）。

全部被擋下時，agent 收到「知識庫裡沒有找到相關的內容」，會照指示回答
找不到資料，而不是自己編造。

**門檻的合適值依模型而定**（不同 embedding 模型的相似度分布差很多），
用 `pyharness knowledge "問題"` 試搜尋，結果會列出每筆的相似度與 rerank
分數，拿相關與不相關的問題各試幾次再決定：

```
$ pyharness knowledge "特休怎麼算"
3 個檔案、12 個片段，檢索方式：BM25 + 語意（embedding），再用 reranker 重新排序
門檻：相似度 ≥ 0.3、rerank ≥ 0.2

[1] 來源：hr/leave.md › 請假規定 › 特休（相似度 0.712、rerank 0.954）
到職滿六個月給三天特休……
```

## 向量資料庫

embedding 存在內建的向量資料庫裡，不需要另外安裝或架設服務：

- 專案的向量存在 `.harness/knowledge/vectors.sqlite3`（一個 SQLite 檔案），
  以「模型名稱 + 片段內容」識別。重新啟動、檔案部分改動時，只有新的
  或改過的片段需要重新計算 embedding；刪掉的檔案，它的向量也會一併
  清掉。舊版的 `embeddings.json` 會自動搬進來。
- 搜尋在記憶體中計算，有安裝 numpy 時用它加速（一萬個片段約 0.02 秒），
  沒有的話用純 Python（幾千個片段以內也很快）：

  ```bash
  pip install numpy
  ```

要改用外部的向量資料庫（pgvector、Qdrant 等），實作
`harness.VectorStore` 的四個方法（`missing`、`add`、`retain`、`search`），
在程式裡交給知識庫：

```python
project = harness.load_project(".")
project.knowledge.vector_store = MyPgVectorStore(...)
```

一個向量資料庫只給一個知識庫使用：`retain` 會刪除這個知識庫用不到的
向量。

## 依部門限制可以搜尋的文件

文件可以標上標籤。**有標籤的文件只有被允許該標籤的 agent 搜尋得到，
沒有標籤的文件所有人都搜尋得到。** 標籤有兩種寫法：

```markdown
---
labels: [hr]
---
# 請假規定
...
```

或在知識庫資料夾的 `labels.yaml` 用路徑樣式指定（PDF、Office 檔案只能
用這種寫法；每個知識庫各有一份，路徑相對於該知識庫的資料夾）：

```yaml
"hr/*": [hr]
"finance/*.pdf": [finance]
```

限制某個 agent 只能搜尋特定標籤：

```markdown
---
name: hr_bot
knowledge:
  labels: [hr]        # 只搜尋得到 hr 與沒有標籤的文件
  topK: 5             # 每次最多回傳幾筆，預設 5
---
```

要依**登入的使用者**決定範圍（例如不同部門看到不同文件），在程式裡
設定 `label_filter`，它收到 `RunContext`，從 `deps` 取得使用者資訊：

```python
project = harness.load_project(".")
project.knowledge.label_filter = lambda context: context.deps["departments"]

await harness.run(agent, text, deps={"departments": ["hr"]})
```

agent 設定的 `labels` 與 `label_filter` 同時存在時，兩者都允許的標籤
才搜尋得到。

用網頁版（`pyharness web`）讓多人登入時不必寫程式：管理者在「管理平台 →
群組」為每個群組勾選可以搜尋的**知識庫**與**標籤**。知識庫是大範圍的權限
（例如人資的知識庫只開放給人資群組），標籤是知識庫裡更細的過濾；成員
搜尋得到的是所屬群組開放的知識庫與標籤，再和 agent 自己的設定取交集
（見[存取群組](/guide/web#存取群組)）。

## 在程式裡使用

```python
kb = harness.Knowledge(
    "knowledge",
    embedding_model="openai/text-embedding-3-small",  # 可省略
    parsers={".html": parse_html},  # 可省略，替換或新增解析器
    cache_dir="data/kb-cache",  # 向量資料庫的位置，省略時只存在記憶體
    min_similarity=0.3,  # 可省略
    reranker="cohere/rerank-v3.5",  # 可省略
    min_rerank_score=0.2,  # 可省略
)
kb.add_text("退貨請在七天內申請", source="FAQ#3")  # 也可以直接加文字

agent = harness.Agent(name="faq", instructions="...", tools=[kb.as_tool()])

hits = await kb.search("退貨期限")  # 也可以直接搜尋
hits[0].similarity, hits[0].rerank_score  # 沒有使用時是 None
```

好幾個知識庫一起搜尋：

```python
from harness import knowledge

bases = [
    knowledge.KnowledgeBase("hr", "人資規章", harness.Knowledge("docs/hr")),
    knowledge.KnowledgeBase("it", "IT 支援", harness.Knowledge("docs/it")),
]
tool = knowledge.search_tool(bases)  # 合併排序的 search_knowledge 工具
hits = await knowledge.search_bases(bases, "VPN 連不上")
hits[0].base  # 結果來自哪個知識庫
```

用自己的 reranker（例如本機的 cross-encoder）時，傳入
`rerank_fn=async (query, documents) -> list[float]`，分數越大越相關。

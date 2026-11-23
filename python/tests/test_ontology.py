"""ontology：定義檔、綁定、五個查詢方法、權限與分級、動作與核准。

用 examples/ontology_demo（虛構的合約管理資料）當測試專案，每個測試複製
一份到臨時資料夾。
"""

import pathlib
import shutil
import sqlite3

import pytest
from aiohttp.test_utils import TestClient
from aiohttp.test_utils import TestServer

import harness
from harness import datatypes
from harness import ontology as ontology_lib
from harness import permissions as permissions_lib
from harness import project as project_lib
from harness.web import audit as audit_lib
from harness.web import server as server_lib
from tests import conftest
from tests.test_web import Harness

DEMO = pathlib.Path(__file__).parents[2] / "examples" / "ontology_demo"


@pytest.fixture
def demo(tmp_path) -> pathlib.Path:
    root = tmp_path / "demo"
    shutil.copytree(DEMO, root, ignore=shutil.ignore_patterns(".harness"))
    return root


@pytest.fixture
def loaded(demo):
    project = project_lib.load_project(demo)
    yield project
    project.close()
    ontology_lib.set_viewer(None)


@pytest.fixture
def ctx(demo) -> datatypes.RunContext:
    return datatypes.RunContext("contracts", demo, "s1")


def write_module(root: pathlib.Path, text: str) -> pathlib.Path:
    folder = root / "ontology"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "m.yaml").write_text(text, encoding="utf-8")
    return folder


class TestSchema:
    def test_demo_loads_with_builtin_report_action(self, loaded):
        schema = loaded.ontology.schema

        assert set(schema.modules) == {"core", "contracts"}
        assert schema.relations["supplies"].inverse == "supplied_by"
        assert ontology_lib.REPORT_ACTION in schema.actions

    def test_all_reference_errors_are_listed_together(self, tmp_path):
        folder = write_module(
            tmp_path,
            """
module: m
documents: [nowhere]
types:
  thing:
    classification: secretish
    properties: {name: {}}
relations:
  owns: {from: thing, to: ghost}
actions:
  go: {target: thing}
metrics:
  n: {count: thing, groupBy: color}
bindings:
  - {type: thing, file: x.csv, links: {flies: a}}
""",
        )

        with pytest.raises(ontology_lib.SchemaError) as caught:
            ontology_lib.load_schema(folder, knowledge_bases=set())

        message = str(caught.value)
        for expected in (
            "nowhere",
            "secretish",
            "ghost",
            "run（處理函式）與 create",
            "color",
            "flies",
        ):
            assert expected in message

    def test_yaml_boolean_keys_and_bad_identifiers(self, tmp_path):
        folder = write_module(tmp_path, "module: Bad-Name\n")

        with pytest.raises(ontology_lib.SchemaError, match="小寫英數字"):
            ontology_lib.load_schema(folder)

    def test_agent_scope_checks_modules_and_levels(self, loaded):
        ontology = loaded.ontology

        assert ontology_lib.agent_scope("a", True, ontology).modules is None
        scope = ontology_lib.agent_scope(
            "a", {"modules": ["core"], "maxClassification": "public"}, ontology
        )
        assert scope == ontology_lib.Scope(("core",), "public")
        with pytest.raises(ValueError, match="不存在的 ontology 模組"):
            ontology_lib.agent_scope("a", ["nope"], ontology)
        with pytest.raises(ValueError, match="maxClassification"):
            ontology_lib.agent_scope(
                "a", {"maxClassification": "top"}, ontology
            )


class TestProject:
    def test_agent_with_ontology_gets_tools_and_schema_summary(self, loaded):
        agent = loaded.agents["contracts"]

        assert [t.name for t in agent.tools] == list(ontology_lib.TOOL_NAMES)
        assert "## 業務物件（ontology）" in agent.instructions
        assert "型別 contract（合約）" in agent.instructions
        assert "關鍵供應商（又稱 重要供應商）" in agent.instructions
        assert loaded.toolsets["ontology"] == agent.tools
        assert "find_entity" not in loaded.tools

    def test_toolset_name_is_reserved(self, demo):
        (demo / "tools").mkdir()
        (demo / "tools" / "ontology.py").write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="保留給 ontology"):
            project_lib.load_project(demo)

    def test_ontology_false_disables_it(self, demo):
        config = demo / "harness.yaml"
        text = config.read_text("utf-8").replace(
            "ontology:\n", "ontology: false\nunused:\n"
        )
        config.write_text(text, encoding="utf-8")
        agent = demo / "agents" / "contracts.md"
        agent.write_text(
            agent.read_text("utf-8").replace("ontology:", "unused:"), "utf-8"
        )

        project = project_lib.load_project(demo)

        assert project.ontology is None
        assert "ontology" not in project.toolsets


class TestBindings:
    async def test_sync_loads_each_binding_once(self, loaded):
        ontology = loaded.ontology

        states = {s.name: s for s in await ontology.sync()}

        assert states["vendors"].objects == 2
        assert states["contracts"].links == 9
        assert states["policy_articles"].links == 1
        assert all(not s.warnings for s in states.values())
        again = {s.name: s.loaded_at for s in await ontology.sync()}
        assert again == {name: s.loaded_at for name, s in states.items()}

    async def test_changed_file_reloads_only_that_binding(self, loaded, demo):
        ontology = loaded.ontology
        before = {s.name: s.loaded_at for s in await ontology.sync()}
        vendors = demo / "data" / "vendors.csv"
        vendors.write_text(
            vendors.read_text("utf-8") + "11112222,丙公司,D,否,\n", "utf-8"
        )

        after = {s.name: s for s in await ontology.sync()}

        assert after["vendors"].objects == 3
        assert after["vendors"].loaded_at != before["vendors"]
        assert after["systems"].loaded_at == before["systems"]
        assert any(
            "評等 不在允許的值裡" in w for w in after["vendors"].warnings
        )

    async def test_values_are_converted_to_property_types(self, loaded):
        ontology = loaded.ontology
        await ontology.sync()

        [vendor] = ontology.store.objects(["vendor"], None, ["12345678"])
        [contract] = ontology.store.objects(["contract"], None, ["C-2024-007"])

        assert vendor.props["critical"] is True
        assert contract.props["end_date"] == "2026-12-31"
        assert contract.valid_from == "2024-07-01"
        assert contract.source["row"] == 2

    async def test_knowledge_binding_makes_one_object_per_article(self, loaded):
        ontology = loaded.ontology
        await ontology.sync()

        [article] = ontology.store.objects(
            ["policy_article"], None, ["OUT-01:第五條"]
        )
        links = ontology.store.links_of(
            "policy_article", [article.id], ["refers_to"], False, None
        )

        assert article.label == "委外管理辦法 第五條"
        assert article.docs == [
            {
                "base": "policies",
                "source": "OUT-01_委外管理辦法.md",
                "location": "第五條",
            }
        ]
        assert [link.to_id for link in links] == ["OUT-01:第三條"]

    async def test_python_binding_with_canonical_records(self, loaded, demo):
        (demo / "ontology" / "loaders.py").write_text(
            "def load(ctx):\n"
            "    ctx.warn('示範警告')\n"
            "    return [{'type': 'department', 'id': 'D09',\n"
            "             'properties': {'name': '稽核室'},\n"
            "             'validTo': '2020-01-01'}]\n",
            encoding="utf-8",
        )
        module = demo / "ontology" / "core.yaml"
        module.write_text(
            module.read_text("utf-8")
            + "  - name: extra\n    run: loaders.py:load\n",
            "utf-8",
        )
        project = project_lib.load_project(demo)

        states = {s.name: s for s in await project.ontology.sync()}

        assert states["extra"].objects == 1
        assert states["extra"].warnings == ("示範警告",)
        found = project.ontology.store.objects(["department"], "2026-01-01")
        assert "D09" not in [item.id for item in found]


class TestQueries:
    async def test_find_without_arguments_lists_types(self, loaded, ctx):
        text = await loaded.ontology.find_entity(ctx)

        assert "contract（合約）：3 筆" in text

    async def test_single_match_shows_detail_with_redaction(self, loaded, ctx):
        text = await loaded.ontology.find_entity(ctx, "合約", "C-2025-001")

        assert "【合約】C-2025-001 客戶關係管理系統雲端服務" in text
        assert "有效期間：2025-01-01 起" in text
        assert "data/contracts.yaml 第 1 筆" in text
        assert "金額（萬元）（amount）：（機密，這個助手不能讀取）" in text
        assert "360" not in text
        assert "適用條文（governed_by） 2 筆" in text

    async def test_where_and_alias_expansion(self, loaded, ctx):
        ontology = loaded.ontology

        active = await ontology.find_entity(
            ctx, "contract", where={"status": "生效中"}
        )
        alias = await ontology.find_entity(ctx, "policy_article", "重要供應商")

        assert "找到 2 筆" in active
        assert "C-2023-002" not in active
        assert "第四條" in alias

    async def test_as_of_hides_contracts_not_yet_valid(self, loaded, ctx):
        text = await loaded.ontology.find_entity(
            ctx, "contract", "C-2025-001", as_of="2024-12-31"
        )

        assert "沒有找到" in text

    async def test_get_related_follows_a_path(self, loaded, ctx):
        text = await loaded.ontology.get_related(
            ctx, "system", "SYS-CRM", ["supplied_by", "contracts"]
        )

        assert (
            "供應商 12345678 甲雲端服務股份有限公司 → 合約 C-2025-001" in text
        )
        assert "C-2023-002" in text

    async def test_get_related_rejects_wrong_starting_type(self, loaded, ctx):
        with pytest.raises(harness.ToolError, match="要從 vendor 出發"):
            await loaded.ontology.get_related(
                ctx, "system", "SYS-CRM", ["supplies"]
            )

    async def test_search_documents_only_in_linked_articles(self, loaded, ctx):
        text = await loaded.ontology.search_documents(
            ctx, "供應商 查核", "contract", "C-2024-007", ["governed_by"]
        )

        assert text.startswith(
            "[1] 來源：採購與委外規章 / OUT-01_委外管理辦法.md › 第五條"
        )
        assert "第四條" not in text
        assert ctx.state  # 編號接續 search_knowledge 的規則

    async def test_count_metric_and_python_metric(self, loaded, ctx):
        ontology = loaded.ontology

        counts = await ontology.get_metric(ctx, "contracts_by_status")
        expiring = await ontology.get_metric(
            ctx, "expiring_contracts", {"days": "3650"}, as_of="2026-01-01"
        )

        assert "生效中 2件、已到期 1件；合計 3件" in counts
        assert '"件數": 2' in expiring

    async def test_metric_params_are_checked(self, loaded, ctx):
        with pytest.raises(harness.ToolError, match="必須是整數"):
            await loaded.ontology.get_metric(
                ctx, "expiring_contracts", {"days": "很多"}
            )


class TestAccess:
    async def test_type_limited_to_groups(self, loaded, ctx, demo):
        module = demo / "ontology" / "core.yaml"
        module.write_text(
            module.read_text("utf-8").replace(
                "    label: 人員\n", "    label: 人員\n    groups: [hr]\n"
            ),
            "utf-8",
        )
        project = project_lib.load_project(demo)
        ontology = project.ontology
        ontology_lib.set_viewer(ontology_lib.Viewer("amy", admin=False))

        hidden = await ontology.find_entity(ctx, "person", "E001")
        related = await ontology.get_related(ctx, "system", "SYS-HR")
        ontology_lib.set_viewer(
            ontology_lib.Viewer("bob", frozenset({"hr"}), admin=False)
        )
        shown = await ontology.find_entity(ctx, "person", "E001")

        assert "沒有 person 這個型別" in hidden
        assert "另有 1 筆因權限或分級沒有顯示" in related
        assert "王小明" in shown
        assert "分機（phone）：（機密" in shown

    async def test_agent_scope_limits_modules(self, loaded, ctx):
        ontology = loaded.ontology
        ontology.scopes["contracts"] = ontology_lib.Scope(("core",), None)

        text = await ontology.find_entity(ctx, "contract", "C-2025-001")

        assert "沒有 contract 這個型別" in text

    async def test_documents_respect_viewer_knowledge_bases(self, loaded, ctx):
        ontology_lib.set_viewer(
            ontology_lib.Viewer("amy", admin=False, knowledge_bases=frozenset())
        )

        text = await loaded.ontology.search_documents(ctx, "續約")

        assert "沒有可以搜尋的文件" in text


class TestActions:
    async def test_check_action_reports_problems_before_approval(
        self, loaded, ctx
    ):
        ontology = loaded.ontology
        await ontology.sync()

        def check(**kwargs):
            values = {
                "action": "request_renewal",
                "params": {"months": 12},
                "reason": "使用者要續約",
                "target_id": "C-2024-007",
            }
            values.update(kwargs)
            return ontology.check_action(
                ctx,
                values["action"],
                values["params"],
                values["reason"],
                values["target_id"],
            )

        assert check() is None
        assert "一定要填 reason" in check(reason=" ")
        assert "不能大於 36" in check(params={"months": 99})
        assert "沒有這些參數" in check(params={"months": 1, "x": 1})
        assert "請給 target_id" in check(target_id=None)
        assert "找不到合約 C-9" in check(target_id="C-9")
        assert "沒有 drop_all 這個動作" in check(action="drop_all")

    async def test_create_action_records_object_link_and_log(self, loaded, ctx):
        ontology = loaded.ontology
        events = []
        ontology.on_action = events.append

        text = await ontology.run_action(
            ctx, "request_renewal", {"months": 12}, "續約一年", "C-2024-007"
        )
        related = await ontology.get_related(ctx, "contract", "C-2024-007")
        await ontology.sync(force=True)
        still = await ontology.get_related(ctx, "contract", "C-2024-007")

        assert "已建立 續約申請" in text
        assert "（動作紀錄第 1 筆）" in text
        assert "12 個月續約申請" in related
        assert "12 個月續約申請" in still
        [entry] = ontology.store.actions()
        assert (entry.action, entry.reason, entry.status) == (
            "request_renewal",
            "續約一年",
            "done",
        )
        assert events[0].status == "done"

    async def test_python_action_writes_file_in_workdir(
        self, loaded, ctx, demo
    ):
        text = await loaded.ontology.run_action(
            ctx,
            "flag_vendor_risk",
            {"level": "高", "finding": "查核逾期"},
            "使用者要求標記",
            "87654321",
        )

        assert text.startswith(harness.PRODUCED_MARKER)
        written = (demo / "風險標記" / "87654321.md").read_text("utf-8")
        assert "使用者要求標記" in written

    async def test_rejected_action_is_logged(self, loaded, ctx):
        ontology = loaded.ontology

        with pytest.raises(harness.ToolError):
            await ontology.run_action(ctx, "request_renewal", {}, "x", "C-1")

        [entry] = ontology.store.actions()
        assert entry.status == "rejected"

    async def test_report_missing_concept_goes_to_candidates(self, loaded, ctx):
        ontology = loaded.ontology

        await ontology.run_action(
            ctx,
            ontology_lib.REPORT_ACTION,
            {"concept": "保證金", "description": "合約的履約保證金"},
            "使用者問到但定義裡沒有",
        )

        [item] = ontology.store.candidates()
        assert item["concept"] == "保證金"

    async def test_action_log_cannot_be_changed(self, loaded, ctx):
        ontology = loaded.ontology
        await ontology.run_action(
            ctx, "request_renewal", {"months": 1}, "測試", "C-2024-007"
        )

        db = sqlite3.connect(ontology.store.path)
        with pytest.raises(sqlite3.DatabaseError, match="只能新增"):
            db.execute("DELETE FROM action_log")
        db.close()


class TestApproval:
    def test_force_approval_ignores_bypass_and_allow_rules(self, loaded):
        run_action = loaded.toolsets["ontology"][-1]

        bypass = permissions_lib.Permissions(mode="bypass", allow=["*"])
        dont_ask = permissions_lib.Permissions(mode="dontAsk")
        deny = permissions_lib.Permissions(mode="bypass", deny=["run_*"])

        assert permissions_lib.check(bypass, run_action) == "ask"
        assert permissions_lib.check(dont_ask, run_action) == "deny"
        assert permissions_lib.check(deny, run_action) == "deny"

    async def test_precheck_error_skips_approval(self, loaded, fake_model):
        asked = []

        async def approver(call, target):
            asked.append(call.name)
            return True

        model = fake_model(
            [
                conftest.tool_response(
                    ("run_action", {"action": "request_renewal", "reason": ""})
                ),
                conftest.text_response("好"),
            ]
        )
        result = await harness.run(
            loaded.agents["contracts"],
            "續約",
            permissions=permissions_lib.Permissions(approver=approver),
            workdir=loaded.root,
            model_fn=model,
        )

        tool_message = model.requests[1]["messages"][-1]["content"]
        assert asked == []
        assert "一定要填 reason" in tool_message
        assert result.output == "好"


async def test_web_approval_is_once_only_and_audited(demo, fake_model):
    call = (
        "run_action",
        {
            "action": "request_renewal",
            "reason": "使用者要續約一年",
            "params": {"months": 12},
            "target_id": "C-2024-007",
        },
    )
    model = fake_model(
        [conftest.tool_response(call), conftest.text_response("已送出")]
    )
    loaded = project_lib.load_project(demo)
    app = server_lib.create_app(loaded, model_fn=model)
    client = TestClient(TestServer(app))
    await client.start_server()
    h = Harness(client, demo, model)
    try:
        await h.listen()
        await h.api("POST", "/sessions", {"text": "幫我續約"})
        approval = (await h.wait_for("approval"))["approval"]

        assert approval["onceOnly"] is True
        assert approval["action"]["label"] == "申請續約"
        assert approval["action"]["target"] == "合約 C-2024-007"
        assert approval["action"]["reason"] == "使用者要續約一年"
        assert await h.decide(approval, "always") == 400
        assert await h.decide(approval, "once") == 200
        await h.wait_for("run_end")
    finally:
        if h._reader is not None:
            h._reader.cancel()
        await client.close()
        loaded.close()

    entries = list(audit_lib.AuditLog.for_project(demo).query(limit=20))
    actions = [entry.action for entry in entries]
    assert "ontology.action" in actions
    assert "approval.decide" in actions

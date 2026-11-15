"""依條文切開法規類文件（知識庫的 chunking: regulation）。"""

import pytest

import harness
from harness import regulation

LAW = """\
金融業運用人工智慧指引
第一章 總則
第一條 為促進金融業妥善運用人工智慧，特訂定本指引。
第二條 本指引所稱人工智慧系統，指以機器為基礎之系統。
前項系統依第一條之目的辦理。
第二章 風險管理
第三條 金融機構應依第二條所定系統之風險程度，建立分級管理機制。
第三條之一 高風險系統應經專責主管核准。
第五條 本指引自發布日施行。
"""

POINTS = """\
人工智慧系統分級辦法
一、目的：為規範本行人工智慧系統之分級。
二、適用範圍：本行各單位。
（一）自行開發之系統。
三、分級：依影響程度分為高、中、低三級。
"""


class TestNumeral:
    @pytest.mark.parametrize(
        ("text", "value"),
        [
            ("12", 12),
            ("十", 10),
            ("十二", 12),
            ("二十", 20),
            ("一百零五", 105),
            ("〇", 0),
            ("甲", -1),
        ],
    )
    def test_arabic_and_chinese(self, text, value):
        assert regulation.numeral(text) == value


class TestSplitRegulation:
    def test_one_chunk_per_article_with_chapter(self):
        chunks = regulation.split_regulation([("", LAW)], 500)

        assert chunks is not None
        locations = [location for location, _ in chunks]
        assert locations == [
            "",
            "第一章 總則 › 第一條",
            "第一章 總則 › 第二條",
            "第二章 風險管理 › 第三條",
            "第二章 風險管理 › 第三條之一",
            "第二章 風險管理 › 第五條",
        ]
        assert chunks[0][1] == "金融業運用人工智慧指引"
        # 章節標題併進該章的第一條。
        assert chunks[1][1].startswith("第一章 總則\n第一條")
        # 內文提到「第一條之目的」「第二條所定」不是新的一條。
        assert "前項系統依第一條之目的辦理。" in chunks[2][1]
        assert "依第二條所定系統" in chunks[3][1]

    def test_points_when_there_are_no_articles(self):
        chunks = regulation.split_regulation([("", POINTS)], 500)

        assert chunks is not None
        assert [location for location, _ in chunks] == [
            "",
            "第一點",
            "第二點",
            "第三點",
        ]
        assert "（一）自行開發之系統。" in chunks[2][1]

    def test_page_where_the_article_starts(self):
        pages = [
            ("第 1 頁", "第一條 甲。\n第二條 乙，"),
            ("第 2 頁", "跨頁的內容。\n第三條 丙。"),
        ]

        chunks = regulation.split_regulation(pages, 500)

        assert chunks == [
            ("第一條（第 1 頁）", "第一條 甲。"),
            ("第二條（第 1 頁）", "第二條 乙，\n跨頁的內容。"),
            ("第三條（第 2 頁）", "第三條 丙。"),
        ]

    def test_fullwidth_and_spaced_numbers(self):
        text = "第 １ 條 甲。\n第 ２ 條 乙。\n第 ３ 條 丙。"

        chunks = regulation.split_regulation([("", text)], 500)

        assert [location for location, _ in chunks or []] == [
            "第1條",
            "第2條",
            "第3條",
        ]

    def test_long_article_is_split_by_sentence(self):
        body = "第一條 " + "應遵守規定。" * 30
        text = f"{body}\n第二條 乙。\n第三條 丙。"

        chunks = regulation.split_regulation([("", text)], 50)

        first = [
            text for location, text in chunks or [] if location == "第一條"
        ]
        assert len(first) > 1
        assert all(len(piece) <= 50 for piece in first)
        assert "".join(first).replace(" ", "") == body.replace(" ", "")

    def test_each_piece_of_a_long_article_has_its_own_page(self):
        pages = [
            ("第 1 頁", "第一條 " + "應遵守規定。" * 8),
            ("第 2 頁", "應定期檢討。" * 8),
            ("第 3 頁", "第二條 乙。\n第三條 丙。"),
        ]

        chunks = regulation.split_regulation(pages, 30)

        first = [
            location for location, _ in chunks or [] if "第一條" in location
        ]
        assert first[0] == "第一條（第 1 頁）"
        assert first[-1] == "第一條（第 2 頁）"

    def test_long_point_is_split_at_sub_items(self):
        pages = [
            (
                "第 1 頁",
                "一、核心原則\n（一）原則三：" + "保護隱私。" * 6,
            ),
            ("第 2 頁", "（二）原則四：" + "確保穩健。" * 6),
            ("第 3 頁", "二、配套。\n三、結語。"),
        ]

        chunks = regulation.split_regulation(pages, 50)

        first = [chunk for chunk in chunks or [] if "第一點" in chunk[0]]
        assert first[-1][0] == "第一點（第 2 頁）"
        assert first[-1][1].startswith("（二）原則四")
        assert "保護隱私" not in first[-1][1]

    def test_appendix_ends_the_chapter_and_points_restart(self):
        pages = [
            ("第 1 頁", "第一章 總則\n一、目的。\n二、範圍。\n三、定義。"),
            ("第 2 頁", "第二章 風險\n一、評估。\n二、監督。"),
            ("第 3 頁", "附錄—核心原則說明\n一、前言。\n二、原則四：穩健性。"),
            ("第 4 頁", "參考資料\n1. 某某報告。"),
        ]

        chunks = regulation.split_regulation(pages, 500)

        assert [location for location, _ in chunks or []] == [
            "第一章 總則 › 第一點（第 1 頁）",
            "第一章 總則 › 第二點（第 1 頁）",
            "第一章 總則 › 第三點（第 1 頁）",
            "第二章 風險 › 第一點（第 2 頁）",
            "第二章 風險 › 第二點（第 2 頁）",
            "附錄—核心原則說明 › 第一點（第 3 頁）",
            "附錄—核心原則說明 › 第二點（第 3 頁）",
            "參考資料（第 4 頁）",
        ]

    def test_table_of_contents_and_running_footers_are_not_headings(self):
        toc = "\n".join(
            [
                "目錄",
                "第一章 總則 ........ 1",
                "第二章 風險 ........ 2",
                "參考資料 ........ 3",
                "附錄-核心原則",
            ]
        )
        pages = [
            ("第 1 頁", toc),
            ("第 2 頁", "第一章 總則\n一、目的。\n二、範圍。\n附件 1-1"),
            ("第 3 頁", "三、定義。\n第三章 其他 12\n附件 1-2"),
            ("第 4 頁", "四、施行。\n附件 1-3"),
        ]

        chunks = regulation.split_regulation(pages, 500)

        assert [location for location, _ in chunks or []] == [
            "第 1 頁",
            "第一章 總則 › 第一點（第 2 頁）",
            "第一章 總則 › 第二點（第 2 頁）",
            "第一章 總則 › 第三點（第 3 頁）",
            "第一章 總則 › 第四點（第 4 頁）",
        ]

    def test_not_a_regulation(self):
        text = "# 會議紀錄\n\n第一條路線比較好。\n一、先做原型。"

        assert regulation.split_regulation([("", text)], 500) is None


class TestKnowledgeChunking:
    async def test_regulation_mode_cites_the_article(self, tmp_path):
        (tmp_path / "law.txt").write_text(LAW, encoding="utf-8")
        kb = harness.Knowledge(tmp_path, chunking="regulation")

        hits = await kb.search("專責主管核准")

        assert hits[0].chunk.location == "第二章 風險管理 › 第三條之一"
        assert hits[0].chunk.text == "第三條之一 高風險系統應經專責主管核准。"

    async def test_other_documents_fall_back_to_paragraphs(self, tmp_path):
        (tmp_path / "note.md").write_text(
            "# 筆記\n\n## 原型\n先做原型再決定。", encoding="utf-8"
        )
        kb = harness.Knowledge(tmp_path, chunking="regulation")

        [hit] = await kb.search("原型")

        assert hit.chunk.location == "筆記 › 原型"

    def test_unknown_mode_is_an_error(self, tmp_path):
        with pytest.raises(ValueError, match="chunking"):
            harness.Knowledge(tmp_path, chunking="sentence")

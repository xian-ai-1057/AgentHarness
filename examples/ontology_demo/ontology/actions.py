"""合約管理模組的動作處理函式（範例）。"""

import pathlib

import harness


def flag_vendor_risk(ctx, level: str, finding: str) -> str:
    """在工作資料夾產生一份風險標記單。

    ctx.target 是指定的供應商，ctx.reason 是使用者核准時看到的理由。
    """
    vendor = ctx.target
    folder = pathlib.Path(ctx.run.workdir) / "風險標記"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{vendor.id}.md"
    path.write_text(
        f"# {vendor.label} 風險標記\n\n"
        f"- 風險等級：{level}\n- 發現：{finding}\n- 理由：{ctx.reason}\n"
        f"- 標記人：{ctx.viewer.user or '本機'}\n",
        encoding="utf-8",
    )
    return f"{harness.PRODUCED_MARKER}風險標記/{vendor.id}.md"

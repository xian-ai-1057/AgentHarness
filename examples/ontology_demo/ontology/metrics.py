"""合約管理模組的指標（範例）。"""

import datetime


def expiring_contracts(ctx, days: int = 90) -> dict:
    """生效中、到期日在 days 天內的合約。"""
    today = datetime.date.fromisoformat(ctx.view.as_of)
    limit = (today + datetime.timedelta(days=days)).isoformat()
    found = [
        {"合約": c.id, "名稱": c.label, "到期日": c.props.get("end_date")}
        for c in ctx.view.objects("contract")
        if c.props.get("status") == "生效中"
        and c.props.get("end_date")
        and ctx.view.as_of <= c.props["end_date"] <= limit
    ]
    return {"天數": days, "件數": len(found), "合約": found}

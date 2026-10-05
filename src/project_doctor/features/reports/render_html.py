import json
from html import escape


def render_html(json_content: str) -> str:
    payload = json.loads(json_content)
    summaries = "".join(
        f"<li>{escape(item['experiment_id'])}：预热成功 {item['warmup_successes']} / "
        f"{item['warmup_attempts']} 次，正式样本 {item['formal_samples']} 条；"
        f"准备验证：{'通过' if item['preparation_verified'] else '未通过'}。"
        f"锁证据状态：{escape(statuses)}。</li>"
        for item in payload.get("measurement_protocols", [])
        for statuses in [
            ", ".join(sorted({lock["status"] for lock in item["lock_statuses"]})) or "unknown"
        ]
    )
    # Both formats show the same structured payload, with no model-generated HTML.
    return (
        '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>Project Doctor 慢查询诊断</title>"
        "<style>body{max-width:1000px;margin:36px auto;padding:0 24px;"
        "font-family:system-ui;line-height:1.6}pre{white-space:pre-wrap;"
        "overflow-wrap:anywhere;background:#f5f7fa;padding:20px}</style>"
        "<h1>慢查询诊断报告</h1><p>影响仅对应本次测试负载。"
        "修改建议未经实施复测均为预计作用机制。</p>"
        f"<h2>测量准备与锁覆盖</h2><ul>{summaries}</ul>"
        "<p>预热不计入正式收益；锁覆盖不足时继续作为线索。</p>"
        f"<pre>{escape(json_content)}</pre></html>"
    )

from html import escape


def render_html(json_content: str) -> str:
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
        f"<pre>{escape(json_content)}</pre></html>"
    )

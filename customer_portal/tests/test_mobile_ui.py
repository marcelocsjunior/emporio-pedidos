def _read_text(path):
    with open(path, encoding="utf-8") as source:
        return source.read()


def test_request_list_mobile_contract():
    base = _read_text("customer_portal/templates/customer_portal/base.html")
    template = _read_text("customer_portal/templates/customer_portal/request_list.html")
    css = _read_text("static/css/customer_portal.css")

    assert base.index("css/mvp03.css") < base.index("css/customer_portal.css")
    assert 'class="page-heading portal-request-heading"' in template
    assert 'class="button primary portal-request-create"' in template
    assert 'class="responsive-table portal-request-table"' in template
    assert 'class="portal-request-action"' in template
    assert 'class="empty-row"' in template

    for label in ("Protocolo", "Entrega", "Status", "Total", "Pedido", "Ação"):
        assert f'data-label="{label}"' in template

    assert "@media (max-width: 700px)" in css
    assert ".portal-request-heading > .portal-request-create" in css
    assert "grid-template-columns: minmax(88px, 34%) minmax(0, 1fr)" in css
    assert "padding: 12px 84px 2px 0" in css
    assert "orientation: landscape" in css
    assert "padding-right: 96px" in css
    assert "(min-width: 701px) and (max-width: 900px)" in css
    assert "(max-height: 500px)" in css
    assert ".portal-request-table thead" in css
    assert "padding: 12px 96px 2px 0" in css

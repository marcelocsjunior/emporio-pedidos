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


def test_request_detail_mobile_contract():
    template = _read_text("customer_portal/templates/customer_portal/request_detail.html")
    css = _read_text("static/css/customer_portal.css")

    assert 'class="portal-detail-page"' in template
    assert 'class="page-heading portal-detail-heading"' in template
    assert 'class="button ghost portal-detail-back"' in template
    assert 'class="detail-grid portal-detail-grid"' in template
    assert 'class="panel portal-detail-panel portal-detail-delivery"' in template
    assert 'class="panel portal-detail-panel portal-detail-progress"' in template
    assert 'class="detail-list portal-detail-list"' in template
    assert 'class="table-wrap portal-detail-items-wrap"' in template
    assert 'class="responsive-table portal-detail-items-table"' in template
    assert 'aria-label="Composição da solicitação"' in template
    assert "table-wrapper" not in template
    assert "return confirm('Cancelar esta solicitação?');" in template

    for label in ("Produto", "Quantidade", "Unitário", "Total"):
        assert f'data-label="{label}"' in template

    assert ".portal-detail-heading > .portal-detail-back" in css
    assert ".portal-detail-list > div" in css
    assert "grid-template-columns: minmax(104px, 32%) minmax(0, 1fr)" in css
    assert ".portal-detail-items-table" in css
    assert ".portal-detail-items-wrap" in css
    assert "font-size: clamp(24px, 7.6vw, 28px)" in css
    assert "grid-template-columns: minmax(88px, 34%) minmax(0, 1fr)" in css
    assert (
        "@media (max-width: 700px) and (orientation: landscape) {\n"
        "  .portal-detail-page {"
    ) in css
    assert (
        "@media (min-width: 701px) and (max-width: 900px) and "
        "(max-height: 500px) and (orientation: landscape) {\n"
        "  .portal-detail-page {"
    ) in css
    assert "padding-right: 96px" in css
    assert ".portal-detail-items-table thead" in css

# app.py
# Streamlit app to convert Grand Brass invoices (PDF) into Craftybase Bulk Expense CSV
import io
import re
import pandas as pd
import streamlit as st
from pdfminer.high_level import extract_text

COLUMNS = [
    'purchase_date','code','material_sku','material_name','vendor','lot_number','notes',
    'line_item_quantity','line_item_category_id','line_item_price','tax','shipping','discount',
    'grand_total','paid'
]

VENDOR_NAME = "Grand Brass Lamp Parts, LLC."

def clean(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", s.strip())

def parse_header(text: str):
    import re
    hdr = {}
    m = re.search(r"Reference No\.\s*([A-Z0-9-]+)", text)
    if m: hdr['invoice_no'] = m.group(1)
    m = re.search(r"\bDate:\s*(\d{1,2}/\d{1,2}/\d{4})", text)
    if m: hdr['purchase_date'] = m.group(1)
    m = re.search(r"SO\s*NUMBER\s*([0-9-]+)", text, re.IGNORECASE)
    if m: hdr['so_number'] = m.group(1)
    m = re.search(r"Shipment Number\s*([0-9-]+)", text, re.IGNORECASE)
    if m: hdr['shipment_number'] = m.group(1)
    m = re.search(r"Tracking\s*#\s*([A-Z0-9]+)", text, re.IGNORECASE)
    if not m:
        m = re.search(r"TRACKING NUMBER\s*\n([A-Z0-9]+)", text)
    if m: hdr['tracking'] = m.group(1)
    return hdr

def parse_lines(text: str):
    import re
    lines = []
    tab_m = re.search(r"NO\.\s*ITEM.*?AMOUNT\n(.*?)\n(?:THANK YOU|Sales Total|Freight Total)", text, re.DOTALL | re.IGNORECASE)
    block = tab_m.group(1) if tab_m else text
    for raw in block.splitlines():
        s = clean(raw)
        if not s:
            continue
        if re.search(r"^(NO\.|ITEM|EACH\s+ORDERED|SHIP VIA|SO TYPE)", s, re.IGNORECASE):
            continue
        if re.search(r"\bFreight\b", s, re.IGNORECASE):
            m_amt = re.search(r"([0-9]+\.[0-9]{2})\s*$", s)
            ship_amt = float(m_amt.group(1)) if m_amt else 0.0
            lines.append({'sku': '', 'name': 'Freight - UPS Ground', 'qty': 1, 'price_subtotal': 0.0, 'shipping': ship_amt})
            continue
        m = re.search(r"^\d+\s+([A-Z0-9-]+):?\s+(.*?)\s+EACH\s+([0-9.-]+)\s+([0-9.-]+)\s+([0-9.-]+)\s+([0-9,.]+)\s+([0-9,.]+)$", s)
        if not m:
            m = re.search(r"^\d+\s+([A-Z0-9-]+):?\s+(.*?)\s+([0-9,.]+)\s+([0-9,.]+)$", s)
            if m:
                sku, desc, unit, amount = m.group(1), m.group(2), m.group(3), m.group(4)
                try:
                    amt_val = float(amount.replace(',', ''))
                except:
                    amt_val = 0.0
                lines.append({'sku': sku, 'name': desc, 'qty': 1, 'price_subtotal': amt_val, 'shipping': 0.0})
                continue
        if m:
            sku = m.group(1)
            desc = m.group(2)
            qty = float(m.group(3)) if m.group(3) else 1
            amount = float(m.group(7).replace(',', '')) if m.group(7) else 0.0
            lines.append({'sku': sku, 'name': desc, 'qty': qty, 'price_subtotal': amount, 'shipping': 0.0})
    return lines

def to_craftybase_rows(meta, items):
    parts = []
    if meta.get('so_number'): parts.append(f"SO {meta['so_number']}")
    if meta.get('shipment_number'): parts.append(f"Shipment {meta['shipment_number']}")
    if meta.get('tracking'): parts.append(f"Tracking {meta['tracking']}")
    notes = " • ".join(parts) if parts else None
    rows = []
    for it in items:
        is_freight = it.get('sku','') == '' and 'freight' in it.get('name','').lower()
        line = {
            'purchase_date': meta.get('purchase_date'),
            'code': meta.get('invoice_no'),
            'material_sku': it.get('sku',''),
            'material_name': it.get('name',''),
            'vendor': VENDOR_NAME,
            'lot_number': '',
            'notes': notes,
            'line_item_quantity': int(it.get('qty') or 1),
            'line_item_category_id': 'Shipping' if is_freight else 'Materials',
            'line_item_price': 0.0 if is_freight else round(float(it.get('price_subtotal') or 0.0), 2),
            'tax': 0.0,
            'shipping': round(float(it.get('shipping') or 0.0), 2),
            'discount': 0.0,
            'grand_total': round(float(it.get('price_subtotal') or 0.0) + float(it.get('shipping') or 0.0), 2),
            'paid': 'Y'
        }
        rows.append(line)
    return pd.DataFrame(rows, columns=COLUMNS)

st.set_page_config(page_title="Invoice → Craftybase CSV", page_icon="📦")
st.title("📦 Invoice → Craftybase CSV")
st.caption("Upload Grand Brass invoice PDFs and get a Craftybase-compatible Bulk Expense CSV.")

with st.expander("How to use", expanded=False):
    st.markdown("""
    1. Click **Browse files** and select one or more **Grand Brass** invoice PDFs.
    2. Review the preview grid.
    3. Click **Download CSV** to save the Craftybase import file.
    """)

uploaded = st.file_uploader("Upload invoice PDFs", type=["pdf"], accept_multiple_files=True)

if uploaded:
    frames = []
    for f in uploaded:
        bytes_data = f.read()
        try:
            text = extract_text(io.BytesIO(bytes_data))
        except Exception as e:
            st.error(f"Failed to read {f.name}: {e}")
            continue
        meta = parse_header(text)
        items = parse_lines(text)
        if not items:
            st.warning(f"No line items detected in {f.name}. Open the Text Preview below to help refine the parser.")
        df = to_craftybase_rows(meta, items)
        df.insert(0, 'source_file', f.name)
        frames.append(df)
        with st.expander(f"Text Preview: {f.name}"):
            st.text(text[:5000])
    if frames:
        result = pd.concat(frames, ignore_index=True)
        st.subheader("Preview")
        st.dataframe(result, use_container_width=True)
        csv = result.drop(columns=['source_file']).to_csv(index=False).encode('utf-8')
        st.download_button("⬇️ Download CSV", data=csv, file_name="craftybase_import.csv", mime="text/csv")
else:
    st.info("Upload one or more Grand Brass PDFs to begin.")

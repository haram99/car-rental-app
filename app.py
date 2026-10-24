"""نظام تأجير السيارات — Streamlit + SQLite.  Run: streamlit run app.py"""
import calendar
import io
import sqlite3
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image

DB_PATH = Path(__file__).parent / "rental.db"
CAR_FREE, CAR_RENTED = "متاحة", "مؤجرة"
CAR_STATUSES = [CAR_FREE, CAR_RENTED, "في الصيانة"]
C_ACTIVE, C_ENDED = "ساري", "منتهي"
PHOTO_TYPES = ["png", "jpg", "jpeg", "webp"]

st.set_page_config(page_title="نظام تأجير السيارات", page_icon="🚗", layout="wide")
st.markdown(
    """<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Arabic:wght@400;500;700&display=swap');
html, body, [data-testid="stAppViewContainer"], [data-testid="stSidebar"], .stMarkdown, label, input, textarea
{direction: rtl; font-family: 'IBM Plex Sans Arabic', sans-serif !important; text-align: right;}
h1, h2, h3 {font-weight: 700;}
</style>""",
    unsafe_allow_html=True,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS cars(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  plate TEXT UNIQUE NOT NULL, model TEXT NOT NULL, year INTEGER,
  color TEXT, status TEXT NOT NULL DEFAULT 'متاحة', notes TEXT);
CREATE TABLE IF NOT EXISTS contracts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  car_id INTEGER NOT NULL REFERENCES cars(id),
  customer TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL,
  months INTEGER NOT NULL, monthly_rate REAL NOT NULL,
  status TEXT NOT NULL DEFAULT 'ساري');
CREATE TABLE IF NOT EXISTS payments(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  contract_id INTEGER NOT NULL REFERENCES contracts(id),
  due_date TEXT NOT NULL, amount REAL NOT NULL, paid_date TEXT);
"""


@st.cache_resource
def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.executescript(SCHEMA)
    if "photo" not in [r[1] for r in conn.execute("PRAGMA table_info(cars)")]:
        conn.execute("ALTER TABLE cars ADD COLUMN photo BLOB")
        conn.commit()
    return conn


def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, get_conn(), params=params)


def run(sql: str, params: tuple = ()) -> None:
    conn = get_conn()
    conn.execute(sql, params)
    conn.commit()


def process_photo(file) -> bytes:
    """Resize to max 900px and re-encode as JPEG so the database stays small."""
    img = Image.open(file).convert("RGB")
    img.thumbnail((900, 900))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def is_photo(x) -> bool:
    return isinstance(x, (bytes, bytearray))


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def flash(msg: str) -> None:
    st.session_state["flash"] = msg
    st.rerun()


def show_flash() -> None:
    if msg := st.session_state.pop("flash", None):
        st.success(msg)


# ---------------------------------------------------------------- pages
def page_dashboard() -> None:
    st.title("لوحة المعلومات")
    today = date.today().isoformat()
    cars = q("SELECT status, COUNT(*) n FROM cars GROUP BY status").set_index("status")["n"]
    pay = q("SELECT SUM(CASE WHEN paid_date IS NOT NULL THEN amount ELSE 0 END) paid,"
            " SUM(CASE WHEN paid_date IS NULL THEN amount ELSE 0 END) due FROM payments").iloc[0]
    overdue = q("SELECT p.id, c.plate AS اللوحة, k.customer AS العميل, p.due_date AS الاستحقاق,"
                " p.amount AS المبلغ FROM payments p JOIN contracts k ON k.id=p.contract_id"
                " JOIN cars c ON c.id=k.car_id WHERE p.paid_date IS NULL AND p.due_date < ?"
                " ORDER BY p.due_date", (today,))
    active = int(q("SELECT COUNT(*) n FROM contracts WHERE status=?", (C_ACTIVE,)).iloc[0, 0])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("إجمالي السيارات", int(cars.sum()) if len(cars) else 0)
    c2.metric("مؤجرة", int(cars.get(CAR_RENTED, 0)))
    c3.metric("متاحة", int(cars.get(CAR_FREE, 0)))
    c4.metric("عقود سارية", active)
    c5, c6, c7 = st.columns(3)
    c5.metric("المحصَّل", f"{(pay['paid'] or 0):,.0f}")
    c6.metric("المتبقي", f"{(pay['due'] or 0):,.0f}")
    c7.metric("أقساط متأخرة", len(overdue))

    monthly = q("SELECT substr(paid_date,1,7) AS الشهر, SUM(amount) AS المحصَّل FROM payments"
                " WHERE paid_date IS NOT NULL GROUP BY 1 ORDER BY 1")
    if not monthly.empty:
        st.subheader("التحصيل الشهري")
        st.bar_chart(monthly.set_index("الشهر"))
    st.subheader("الأقساط المتأخرة")
    if overdue.empty:
        st.info("لا توجد أقساط متأخرة.")
    else:
        st.dataframe(overdue.drop(columns="id"), use_container_width=True, hide_index=True)


def page_cars() -> None:
    st.title("السيارات")
    with st.form("add_car", clear_on_submit=True):
        st.subheader("إضافة سيارة")
        a, b, c = st.columns(3)
        plate = a.text_input("رقم اللوحة")
        model = b.text_input("الموديل (مثال: MG5)")
        year = c.number_input("سنة الصنع", 1990, 2100, 2022)
        d, e = st.columns(2)
        color = d.text_input("اللون")
        notes = e.text_input("ملاحظات")
        photo = st.file_uploader("صورة السيارة", type=PHOTO_TYPES)
        if st.form_submit_button("إضافة", type="primary"):
            if not plate.strip() or not model.strip():
                st.error("رقم اللوحة والموديل مطلوبان.")
            else:
                try:
                    blob = process_photo(photo) if photo else None
                    run("INSERT INTO cars(plate,model,year,color,notes,photo) VALUES(?,?,?,?,?,?)",
                        (plate.strip(), model.strip(), int(year), color.strip(), notes.strip(), blob))
                    flash(f"تمت إضافة السيارة {plate.strip()}.")
                except sqlite3.IntegrityError:
                    st.error("رقم اللوحة موجود مسبقًا.")
    show_flash()

    df = q("SELECT id, plate AS اللوحة, model AS الموديل, year AS السنة, color AS اللون,"
           " status AS الحالة, notes AS ملاحظات FROM cars ORDER BY id DESC")
    if df.empty:
        st.info("لم تُضف أي سيارة بعد.")
        return
    gallery = q("SELECT plate, model, status, photo FROM cars ORDER BY id DESC")
    cols = st.columns(3)
    for i, r in enumerate(gallery.itertuples()):
        with cols[i % 3]:
            if is_photo(r.photo):
                st.image(r.photo, use_container_width=True)
            else:
                st.caption("(لا توجد صورة)")
            st.markdown(f"**{r.plate}** — {r.model} · {r.status}")
    st.dataframe(df.drop(columns="id"), use_container_width=True, hide_index=True)

    st.subheader("تعديل أو حذف")
    labels = {int(r.id): f"{r['اللوحة']} — {r['الموديل']}" for _, r in df.iterrows()}
    car_id = st.selectbox("اختر السيارة", list(labels), format_func=labels.get)
    cur = df[df.id == car_id].iloc[0]
    cur_photo = q("SELECT photo FROM cars WHERE id=?", (int(car_id),)).iloc[0, 0]
    if is_photo(cur_photo):
        st.image(cur_photo, width=320)
    n = st.session_state.get("up_n", 0)
    new_photo = st.file_uploader("صورة جديدة للسيارة", type=PHOTO_TYPES, key=f"up_{car_id}_{n}")
    p1, p2 = st.columns(2)
    if p1.button("حفظ الصورة") and new_photo:
        run("UPDATE cars SET photo=? WHERE id=?", (process_photo(new_photo), int(car_id)))
        st.session_state["up_n"] = n + 1
        flash("تم حفظ الصورة.")
    if p2.button("حذف الصورة"):
        run("UPDATE cars SET photo=NULL WHERE id=?", (int(car_id),))
        flash("تم حذف الصورة.")
    col1, col2, col3 = st.columns([2, 1, 1])
    status = col1.selectbox("الحالة", CAR_STATUSES, index=CAR_STATUSES.index(cur["الحالة"]))
    if col2.button("حفظ الحالة"):
        run("UPDATE cars SET status=? WHERE id=?", (status, int(car_id)))
        flash("تم تحديث الحالة.")
    if col3.button("حذف السيارة"):
        used = q("SELECT COUNT(*) n FROM contracts WHERE car_id=?", (int(car_id),)).iloc[0, 0]
        if used:
            st.error("لا يمكن حذف سيارة لها عقود. غيّر حالتها بدلًا من ذلك.")
        else:
            run("DELETE FROM cars WHERE id=?", (int(car_id),))
            flash("تم حذف السيارة.")


def page_contracts() -> None:
    st.title("عقود الإيجار")
    free = q("SELECT id, plate, model FROM cars WHERE status=? ORDER BY plate", (CAR_FREE,))
    if free.empty:
        st.warning("لا توجد سيارات متاحة. أضف سيارة أو أنهِ عقدًا قائمًا.")
    else:
        labels = {int(r.id): f"{r.plate} — {r.model}" for r in free.itertuples()}
        with st.form("add_contract", clear_on_submit=True):
            st.subheader("عقد جديد")
            car_id = st.selectbox("السيارة", list(labels), format_func=labels.get)
            customer = st.text_input("العميل / الجهة المستأجرة")
            a, b, c = st.columns(3)
            start = a.date_input("تاريخ البداية", date.today())
            months = b.number_input("المدة بالأشهر", 1, 120, 12)
            rate = c.number_input("القسط الشهري", 0.0, 1_000_000.0, 0.0, step=50.0)
            if st.form_submit_button("إنشاء العقد وجدولة الأقساط", type="primary"):
                if not customer.strip() or rate <= 0:
                    st.error("اسم العميل والقسط الشهري مطلوبان.")
                else:
                    conn = get_conn()
                    cur = conn.execute(
                        "INSERT INTO contracts(car_id,customer,start_date,end_date,months,monthly_rate)"
                        " VALUES(?,?,?,?,?,?)",
                        (int(car_id), customer.strip(), start.isoformat(),
                         add_months(start, int(months)).isoformat(), int(months), float(rate)))
                    conn.executemany(
                        "INSERT INTO payments(contract_id,due_date,amount) VALUES(?,?,?)",
                        [(cur.lastrowid, add_months(start, i).isoformat(), float(rate))
                         for i in range(int(months))])
                    conn.execute("UPDATE cars SET status=? WHERE id=?", (CAR_RENTED, int(car_id)))
                    conn.commit()
                    flash(f"تم إنشاء العقد مع {int(months)} قسطًا.")
    show_flash()

    df = q("SELECT k.id, c.plate AS اللوحة, c.model AS الموديل, k.customer AS العميل,"
           " k.start_date AS البداية, k.end_date AS النهاية, k.months AS الأشهر,"
           " k.monthly_rate AS القسط, k.status AS الحالة FROM contracts k"
           " JOIN cars c ON c.id=k.car_id ORDER BY k.id DESC")
    if df.empty:
        st.info("لا توجد عقود بعد.")
        return
    st.dataframe(df.drop(columns="id"), use_container_width=True, hide_index=True)

    act = df[df["الحالة"] == C_ACTIVE]
    if not act.empty:
        st.subheader("إنهاء عقد")
        labels = {int(r.id): f"{r['اللوحة']} — {r['العميل']}" for _, r in act.iterrows()}
        cid = st.selectbox("العقد", list(labels), format_func=labels.get)
        if st.button("إنهاء العقد وإتاحة السيارة"):
            conn = get_conn()
            conn.execute("UPDATE contracts SET status=? WHERE id=?", (C_ENDED, int(cid)))
            conn.execute("UPDATE cars SET status=? WHERE id=(SELECT car_id FROM contracts WHERE id=?)",
                         (CAR_FREE, int(cid)))
            conn.commit()
            flash("تم إنهاء العقد، والسيارة متاحة الآن.")


def page_payments() -> None:
    st.title("الأقساط والدفعات")
    today = date.today().isoformat()
    show_flash()
    flt = st.radio("عرض", ["غير المدفوعة", "المتأخرة", "المدفوعة", "الكل"], horizontal=True)
    where = {"غير المدفوعة": "p.paid_date IS NULL",
             "المتأخرة": f"p.paid_date IS NULL AND p.due_date < '{today}'",
             "المدفوعة": "p.paid_date IS NOT NULL", "الكل": "1=1"}[flt]
    df = q("SELECT p.id, c.plate AS اللوحة, k.customer AS العميل, p.due_date AS الاستحقاق,"
           " p.amount AS المبلغ, p.paid_date AS تاريخ_السداد FROM payments p"
           " JOIN contracts k ON k.id=p.contract_id JOIN cars c ON c.id=k.car_id"
           f" WHERE {where} ORDER BY p.due_date")
    if df.empty:
        st.info("لا توجد أقساط ضمن هذا العرض.")
        return
    st.dataframe(df.drop(columns="id"), use_container_width=True, hide_index=True)

    unpaid = df[df["تاريخ_السداد"].isna()]
    if not unpaid.empty:
        st.subheader("تسجيل دفعة")
        labels = {int(r.id): f"{r['اللوحة']} — {r['العميل']} — {r['الاستحقاق']} — {r['المبلغ']:,.0f}"
                  for _, r in unpaid.iterrows()}
        pid = st.selectbox("القسط", list(labels), format_func=labels.get)
        paid_on = st.date_input("تاريخ السداد", date.today())
        if st.button("تسجيل السداد", type="primary"):
            run("UPDATE payments SET paid_date=? WHERE id=?", (paid_on.isoformat(), int(pid)))
            flash("تم تسجيل الدفعة.")


def page_backup() -> None:
    st.title("النسخ الاحتياطي")
    st.caption("على الاستضافة المجانية قد تُمسح البيانات عند إعادة تشغيل التطبيق، فنزّل نسخة بانتظام.")
    show_flash()
    conn = get_conn()
    conn.commit()
    st.download_button("تنزيل قاعدة البيانات (.db)", DB_PATH.read_bytes(), "rental_backup.db")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        for name in ("cars", "contracts", "payments"):
            sql = ("SELECT id, plate, model, year, color, status, notes FROM cars"
                   if name == "cars" else f"SELECT * FROM {name}")
            q(sql).to_excel(xw, sheet_name=name, index=False)
    st.download_button("تنزيل Excel", buf.getvalue(), "rental_export.xlsx")
    st.subheader("استعادة نسخة")
    up = st.file_uploader("ارفع ملف .db", type=["db"])
    if up and st.button("استعادة (تستبدل البيانات الحالية)"):
        data = up.getvalue()
        if not data.startswith(b"SQLite format 3"):
            st.error("الملف ليس قاعدة بيانات صالحة.")
        else:
            conn.close()
            DB_PATH.write_bytes(data)
            st.cache_resource.clear()
            flash("تمت الاستعادة.")


PAGES = {"لوحة المعلومات": page_dashboard, "السيارات": page_cars,
         "العقود": page_contracts, "الأقساط": page_payments, "النسخ الاحتياطي": page_backup}
st.sidebar.title("نظام تأجير السيارات")
PAGES[st.sidebar.radio("القائمة", list(PAGES))]()

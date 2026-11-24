import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, date
import io

st.set_page_config(page_title="Gestionale SRL • BAGLI & TROPEA", page_icon="🏛️", layout="wide")

SOCIO_1 = "BAGLI"
SOCIO_2 = "TROPEA"

st.markdown("""
<style>
    .stApp { background-color: #f4f6f9; }
    div[data-testid="stMetric"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 16px 20px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
    }
    .card-socio {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 14px;
        padding: 20px;
        box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05);
        margin-bottom: 16px;
    }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] {
        background-color: #ffffff;
        border-radius: 8px 8px 0px 0px;
        padding: 10px 18px;
        border: 1px solid #e2e8f0;
    }
    .stTabs [aria-selected="true"] {
        background-color: #0f172a !important;
        color: #ffffff !important;
    }
    h1, h2, h3 { color: #0f172a; font-family: 'Segoe UI', sans-serif; }
</style>
""", unsafe_allow_html=True)

def check_password():
    if "autenticato" not in st.session_state:
        st.session_state.autenticato = False

    if not st.session_state.autenticato:
        c1, c2, c3 = st.columns([1, 1.2, 1])
        with c2:
            st.markdown("<br><br>", unsafe_allow_html=True)
            st.title("🔐 Accesso Gestionale SRL")
            st.caption("Area Riservata • BAGLI & TROPEA")
            pwd = st.text_input("Inserisci la password aziendale:", type="password")
            if st.button("Entra", type="primary", use_container_width=True):
                password_corretta = st.secrets.get("APP_PASSWORD", "admin123")
                if pwd == password_corretta:
                    st.session_state.autenticato = True
                    st.rerun()
                else:
                    st.error("Password errata.")
        return False
    return True

def get_connection():
    return psycopg2.connect(st.secrets["DATABASE_URL"])

def inizializza_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS fatture (
            id SERIAL PRIMARY KEY,
            tipo TEXT,
            num TEXT,
            anagrafica TEXT,
            imponibile REAL,
            iva_perc INTEGER,
            socio TEXT,
            ritenuta_perc INTEGER DEFAULT 0,
            costo_dipendenti REAL DEFAULT 0.0,
            data_doc TEXT
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS acconti_scadenze (
            id SERIAL PRIMARY KEY,
            data_scadenza TEXT,
            tipologia TEXT,
            riferimento TEXT,
            socio TEXT,
            importo REAL,
            stato TEXT,
            note TEXT
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()
def normalizza_e_controlla_data(data_str, scelta, anno_sel, mese_o_semestre_sel):
    if not data_str:
        return False
    dt = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(str(data_str).strip(), fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return False
    if scelta == "Tutto lo Storico":
        return True
    if str(dt.year) != str(anno_sel):
        return False
    if scelta == "Annuale":
        return True
    if scelta == "Mensile":
        mesi = {"Gennaio": 1, "Febbraio": 2, "Marzo": 3, "Aprile": 4, "Maggio": 5, "Giugno": 6,
                "Luglio": 7, "Agosto": 8, "Settembre": 9, "Ottobre": 10, "Novembre": 11, "Dicembre": 12}
        return dt.month == mesi.get(mese_o_semestre_sel, 1)
    if scelta == "Semestrale":
        return (1 <= dt.month <= 6) if "1°" in mese_o_semestre_sel else (7 <= dt.month <= 12)
    return False

def calcola_metriche_soci(righe, scelta, anno_sel, mese_semestre_sel):
    res = {
        SOCIO_1: {"imp_emesso": 0.0, "iva_debito": 0.0, "imp_ricevuto": 0.0, "iva_credito": 0.0,
                  "ritenuta_subita": 0.0, "ritenuta_da_versare": 0.0, "costo_dipendenti": 0.0,
                  "nota_credito_storno": 0.0, "nota_credito_iva": 0.0, "valore_omaggi": 0.0},
        SOCIO_2: {"imp_emesso": 0.0, "iva_debito": 0.0, "imp_ricevuto": 0.0, "iva_credito": 0.0,
                  "ritenuta_subita": 0.0, "ritenuta_da_versare": 0.0, "costo_dipendenti": 0.0,
                  "nota_credito_storno": 0.0, "nota_credito_iva": 0.0, "valore_omaggi": 0.0}
    }
    for riga in righe:
        if not normalizza_e_controlla_data(riga["data_doc"], scelta, anno_sel, mese_semestre_sel):
            continue
        socio = riga["socio"]
        tipo = riga["tipo"]
        imponibile = float(riga["imponibile"] or 0.0)
        iva_perc = int(riga["iva_perc"] or 0)
        rit_perc = int(riga["ritenuta_perc"] or 0)
        c_dip = float(riga["costo_dipendenti"] or 0.0)

        if socio in res:
            iva = imponibile * (iva_perc / 100)
            ritenuta = imponibile * (rit_perc / 100)
            if tipo == "EMESSA":
                res[socio]["imp_emesso"] += imponibile
                res[socio]["iva_debito"] += iva
                res[socio]["ritenuta_subita"] += ritenuta
            elif tipo == "RICEVUTA":
                res[socio]["imp_ricevuto"] += imponibile
                res[socio]["iva_credito"] += iva
                res[socio]["ritenuta_da_versare"] += ritenuta
                res[socio]["costo_dipendenti"] += c_dip
            elif tipo == "OMAGGIO_FORNITORE":
                res[socio]["valore_omaggi"] += imponibile
                res[socio]["iva_credito"] += iva
            elif tipo == "NOTA_CREDITO":
                res[socio]["nota_credito_storno"] += imponibile
                res[socio]["nota_credito_iva"] += iva

    for s in res:
        res[s]["iva_bilancio"] = (res[s]["iva_debito"] - res[s]["nota_credito_iva"]) - res[s]["iva_credito"]
        res[s]["utile_netto"] = res[s]["imp_emesso"] - res[s]["nota_credito_storno"] - res[s]["imp_ricevuto"] - res[s]["costo_dipendenti"]
        iva_esigibile = res[s]["iva_bilancio"] if res[s]["iva_bilancio"] > 0 else 0.0
        res[s]["liquidita_cassa"] = res[s]["utile_netto"] - res[s]["ritenuta_subita"] - iva_esigibile

    return res[SOCIO_1], res[SOCIO_2]

if check_password():
    inizializza_db()

    with st.sidebar:
        st.title("🏛️ SRL Control Pro")
        st.caption("BAGLI & TROPEA • Cloud Condiviso")
        menu = st.radio("Navigazione", [
            "📊 Cruscotto & Bilancio",
            "📒 Prima Nota & Fatture",
            "🧾 Liquidazione IVA",
            "📅 Acconti & Scadenze F24",
            "📥 Importa / Esporta Excel"
        ])
        st.divider()
        st.subheader("Filtro Periodo")
        scelta_periodo = st.selectbox("Tipo Periodo", ["Tutto lo Storico", "Annuale", "Semestrale", "Mensile"])
        anno_sel = st.selectbox("Anno", [str(a) for a in range(datetime.now().year, 2020, -1)])
        mese_semestre_sel = ""
        if scelta_periodo == "Mensile":
            mesi_nomi = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                         "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
            mese_semestre_sel = st.selectbox("Mese", mesi_nomi, index=datetime.now().month - 1)
        elif scelta_periodo == "Semestrale":
            mese_semestre_sel = st.selectbox("Semestre", ["1° Semestre (Gen-Giu)", "2° Semestre (Lug-Dic)"])

        st.divider()
        if st.button("🔒 Esci / Blocca", use_container_width=True):
            st.session_state.autenticato = False
            st.rerun()

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM fatture ORDER BY id DESC")
    righe_db = cur.fetchall()
    cur.execute("SELECT * FROM acconti_scadenze ORDER BY data_scadenza ASC")
    righe_acc = cur.fetchall()
    cur.close()
    conn.close()

    sb, sl = calcola_metriche_soci(righe_db, scelta_periodo, anno_sel, mese_semestre_sel)

    if menu == "📊 Cruscotto & Bilancio":
        st.title("📊 Cruscotto Direzionale SRL")

        tot_incassi = sb["imp_emesso"] + sl["imp_emesso"]
        tot_utile = sb["utile_netto"] + sl["utile_netto"]
        tot_iva = sb["iva_bilancio"] + sl["iva_bilancio"]
        tot_cassa = sb["liquidita_cassa"] + sl["liquidita_cassa"]

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("💰 Incassi Lordi SRL", f"€ {tot_incassi:,.2f}")
        k2.metric("📈 Utile Netto SRL", f"€ {tot_utile:,.2f}")
        k3.metric("🧾 Posizione IVA SRL", f"€ {abs(tot_iva):,.2f}",
                  delta="A Debito (F24)" if tot_iva > 0 else "A Credito",
                  delta_color="inverse" if tot_iva > 0 else "normal")
        k4.metric("💵 Liquidità Cassa SRL", f"€ {tot_cassa:,.2f}")

        st.markdown("<br>", unsafe_allow_html=True)
        col1, col2 = st.columns(2)
        for col, socio, dati in [(col1, SOCIO_1, sb), (col2, SOCIO_2, sl)]:
            with col:
                st.markdown(f"<div class='card-socio'><h3>👤 Rendiconto: {socio}</h3></div>", unsafe_allow_html=True)
                m1, m2 = st.columns(2)
                m1.metric("Incassi Lordi", f"€ {dati['imp_emesso']:,.2f}")
                m2.metric("Utile Netto", f"€ {dati['utile_netto']:,.2f}")

                st.info(
                    f"**Spese Fornitori:** € {dati['imp_ricevuto']:,.2f} | **Dipendenti:** € {dati['costo_dipendenti']:,.2f}\n\n"
                    f"**Note di Credito:** € {dati['nota_credito_storno']:,.2f} | **Omaggi:** € {dati['valore_omaggi']:,.2f}\n\n"
                    f"**IVA Debito:** € {dati['iva_debito']:,.2f} | **IVA Credito:** € {dati['iva_credito']:,.2f}\n\n"
                    f"**Liquidazione IVA ({'DA VERSARE' if dati['iva_bilancio']>=0 else 'A CREDITO'}):** € {abs(dati['iva_bilancio']):,.2f}\n\n"
                    f"**Ritenute Subite:** € {dati['ritenuta_subita']:,.2f} | **Da Versare (F24):** € {dati['ritenuta_da_versare']:,.2f}\n\n"
                    f"💵 **LIQUIDITÀ DI CASSA STIMATA:** € {dati['liquidita_cassa']:,.2f}"
                )

        st.divider()
        st.subheader("📈 Confronto Visivo BAGLI vs TROPEA")
        df_comp = pd.DataFrame({
            "Voce": ["Incassi Lordi", "Spese Fornitori", "Costo Dipendenti", "Utile Netto", "Liquidità Cassa"],
            SOCIO_1: [sb["imp_emesso"], sb["imp_ricevuto"], sb["costo_dipendenti"], sb["utile_netto"], sb["liquidita_cassa"]],
            SOCIO_2: [sl["imp_emesso"], sl["imp_ricevuto"], sl["costo_dipendenti"], sl["utile_netto"], sl["liquidita_cassa"]]
        })
        fig = go.Figure(data=[
            go.Bar(name=SOCIO_1, x=df_comp["Voce"], y=df_comp[SOCIO_1], marker_color="#0f172a"),
            go.Bar(name=SOCIO_2, x=df_comp["Voce"], y=df_comp[SOCIO_2], marker_color="#3b82f6")
        ])
        fig.update_layout(barmode="group", plot_bgcolor="white", paper_bgcolor="white", height=360)
        st.plotly_chart(fig, use_container_width=True)
    elif menu == "📒 Prima Nota & Fatture":
        st.title("📒 Prima Nota & Registro Fatture")
        t1, t2 = st.tabs(["➕ Nuova Registrazione", "📋 Storico & Modifica"])

        with t1:
            with st.form("nuova_fattura_form", clear_on_submit=True):
                c1, c2, c3, c4 = st.columns(4)
                tipo = c1.selectbox("Tipo Documento", ["EMESSA", "RICEVUTA", "NOTA_CREDITO", "OMAGGIO_FORNITORE"])
                socio = c2.selectbox("Centro / Socio", [SOCIO_1, SOCIO_2])
                data_doc = c3.date_input("Data Documento", date.today())
                num = c4.text_input("Numero Documento")

                c5, c6 = st.columns(2)
                anagrafica = c5.text_input("Cliente / Fornitore / Descrizione")
                imponibile = c6.number_input("Imponibile (€)", min_value=0.0, step=10.0, format="%.2f")

                c7, c8, c9 = st.columns(3)
                iva_perc = c7.selectbox("Aliquota IVA (%)", [22, 10, 4, 0])
                ritenuta_perc = c8.selectbox("Ritenuta d'Acconto (%)", [0, 20, 4])
                costo_dip = c9.number_input("Di cui Costo Dipendenti (€)", min_value=0.0, step=10.0, format="%.2f")

                if st.form_submit_button("Salva Registrazione", type="primary"):
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO fatture (tipo, num, anagrafica, imponibile, iva_perc, socio, ritenuta_perc, costo_dipendenti, data_doc)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                        (tipo, num, anagrafica, imponibile, iva_perc, socio, ritenuta_perc, costo_dip, str(data_doc))
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success("Movimento registrato correttamente nel database cloud!")
                    st.rerun()

        with t2:
            if righe_db:
                df_reg = pd.DataFrame(righe_db)
                st.dataframe(df_reg, use_container_width=True, hide_index=True)

                with st.expander("🗑️ Elimina una registrazione per ID"):
                    id_del = st.number_input("ID da eliminare", min_value=1, step=1)
                    if st.button("Conferma Eliminazione", type="primary"):
                        conn = get_connection()
                        cur = conn.cursor()
                        cur.execute("DELETE FROM fatture WHERE id = %s", (id_del,))
                        conn.commit()
                        cur.close()
                        conn.close()
                        st.warning(f"Registrazione ID {id_del} eliminata.")
                        st.rerun()
            else:
                st.info("Nessuna fattura presente nel database.")

    elif menu == "🧾 Liquidazione IVA":
        st.title("🧾 Riepilogo e Liquidazione IVA")

        c1, c2, c3 = st.columns(3)
        c1.metric(f"IVA Bilancio {SOCIO_1}", f"€ {abs(sb['iva_bilancio']):,.2f}",
                  delta="Da Versare" if sb["iva_bilancio"] > 0 else "A Credito",
                  delta_color="inverse" if sb["iva_bilancio"] > 0 else "normal")
        c2.metric(f"IVA Bilancio {SOCIO_2}", f"€ {abs(sl['iva_bilancio']):,.2f}",
                  delta="Da Versare" if sl["iva_bilancio"] > 0 else "A Credito",
                  delta_color="inverse" if sl["iva_bilancio"] > 0 else "normal")
        tot_iva_srl = sb["iva_bilancio"] + sl["iva_bilancio"]
        c3.metric("TOTALE IVA SRL", f"€ {abs(tot_iva_srl):,.2f}",
                  delta="F24 da Versare" if tot_iva_srl > 0 else "Credito IVA SRL",
                  delta_color="inverse" if tot_iva_srl > 0 else "normal")

        df_iva = pd.DataFrame([
            {"Centro": SOCIO_1, "IVA Debito (€)": sb["iva_debito"], "Storno IVA NC (€)": sb["nota_credito_iva"],
             "IVA Credito (€)": sb["iva_credito"], "Saldo IVA (€)": sb["iva_bilancio"]},
            {"Centro": SOCIO_2, "IVA Debito (€)": sl["iva_debito"], "Storno IVA NC (€)": sl["nota_credito_iva"],
             "IVA Credito (€)": sl["iva_credito"], "Saldo IVA (€)": sl["iva_bilancio"]},
        ])
        st.dataframe(df_iva, use_container_width=True, hide_index=True)

    elif menu == "📅 Acconti & Scadenze F24":
        st.title("📅 Gestione Acconti & Scadenzario F24")
        col_sx, col_dx = st.columns([1, 1.5])

        with col_sx:
            st.subheader("➕ Nuovo Acconto / F24")
            with st.form("form_acconti", clear_on_submit=True):
                d_scad = st.date_input("Data Scadenza", date.today())
                tipologia = st.selectbox("Tipologia", [
                    "Acconto IRES", "Acconto IRAP", "Acconto IVA (27 Dicembre)",
                    "F24 Ritenute / INPS", "Acconto Fornitore", "Acconto Cliente", "Altro"
                ])
                socio_acc = st.selectbox("Riferimento", ["SRL Generale", SOCIO_1, SOCIO_2])
                rif = st.text_input("Descrizione / Codice Tributo")
                importo_acc = st.number_input("Importo (€)", min_value=0.0, step=50.0)
                stato_acc = st.selectbox("Stato", ["Da Pagare", "Pagato"])
                note_acc = st.text_input("Note")

                if st.form_submit_button("Salva Acconto", type="primary"):
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute(
                        """INSERT INTO acconti_scadenze (data_scadenza, tipologia, riferimento, socio, importo, stato, note)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                        (str(d_scad), tipologia, rif, socio_acc, importo_acc, stato_acc, note_acc)
                    )
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success("Acconto registrato!")
                    st.rerun()

        with col_dx:
            st.subheader("📋 Scadenze e Acconti Registrati")
            if righe_acc:
                df_acc = pd.DataFrame(righe_acc)
                st.dataframe(df_acc, use_container_width=True, hide_index=True)
                id_acc = st.number_input("ID Acconto da aggiornare/eliminare", min_value=1, step=1)
                b1, b2 = st.columns(2)
                if b1.button("✅ Segna Pagato"):
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("UPDATE acconti_scadenze SET stato='Pagato' WHERE id=%s", (id_acc,))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.rerun()
                if b2.button("🗑️ Elimina Acconto"):
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute("DELETE FROM acconti_scadenze WHERE id=%s", (id_acc,))
                    conn.commit()
                    cur.close()
                    conn.close()
                    st.rerun()
            else:
                st.info("Nessun acconto registrato.")

    elif menu == "📥 Importa / Esporta Excel":
        st.title("📥 Esportazione e Importazione Dati")
        if righe_db:
            df_exp = pd.DataFrame(righe_db)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                df_exp.to_excel(writer, index=False, sheet_name="PrimaNota_SRL")
            st.download_button(
                label="📥 Scarica Tutto lo Storico in Excel (.xlsx)",
                data=buffer.getvalue(),
                file_name=f"Contabilita_SRL_{date.today()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                type="primary"
            )
        else:
            st.info("Nessun dato da esportare.")

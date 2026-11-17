import streamlit as st
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import io
import sqlite3
import tempfile
import os

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="Contabilità BAGLI & TROPEA", page_icon="📊", layout="wide")

SOCIO_1 = "BAGLI"
SOCIO_2 = "TROPEA"

# --- PROTEZIONE CON PASSWORD ---
def check_password():
    if "autenticato" not in st.session_state:
        st.session_state.autenticato = False

    if not st.session_state.autenticato:
        st.title("🔐 Accesso Gestionale Contabile")
        pwd = st.text_input("Inserisci la password aziendale:", type="password")
        if st.button("Entra"):
            password_corretta = st.secrets.get("APP_PASSWORD", "admin123")
            if pwd == password_corretta:
                st.session_state.autenticato = True
                st.rerun()
            else:
                st.error("Password errata.")
        return False
    return True

# --- CONNESSIONE AL DATABASE CLOUD (POSTGRESQL) ---
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
    conn.commit()
    cur.close()
    conn.close()

def aggiungi_fattura_db(tipo, num, anagrafica, imponibile, iva_perc, socio, ritenuta_perc=0, costo_dipendenti=0.0, data_doc=""):
    if not data_doc:
        data_doc = datetime.now().strftime("%Y-%m-%d")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO fatture (tipo, num, anagrafica, imponibile, iva_perc, socio, ritenuta_perc, costo_dipendenti, data_doc) 
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (tipo, num, anagrafica, imponibile, iva_perc, socio, ritenuta_perc, costo_dipendenti, data_doc)
    )
    conn.commit()
    cur.close()
    conn.close()

# --- LOGICA DI FILTRO E CALCOLO ---
def normalizza_e_controlla_data(data_str, scelta, anno_sel, mese_o_semestre_sel):
    if not data_str:
        return False
    dt = None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(str(data_str).strip()[:10], fmt)
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
        SOCIO_1: {"imp_emesso": 0.0, "iva_debito": 0.0, "imp_ricevuto": 0.0, "iva_credito": 0.0, "ritenuta_subita": 0.0, "ritenuta_da_versare": 0.0, "costo_dipendenti": 0.0, "nota_credito_storno": 0.0, "nota_credito_iva": 0.0, "valore_omaggi": 0.0},
        SOCIO_2: {"imp_emesso": 0.0, "iva_debito": 0.0, "imp_ricevuto": 0.0, "iva_credito": 0.0, "ritenuta_subita": 0.0, "ritenuta_da_versare": 0.0, "costo_dipendenti": 0.0, "nota_credito_storno": 0.0, "nota_credito_iva": 0.0, "valore_omaggi": 0.0}
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

# --- INTERFACCIA WEB PRINCIPALE ---
if check_password():
    inizializza_db()

    st.sidebar.title("CONTABILITÀ IMPRESA")
    st.sidebar.subheader("Configurazione Periodo")
    
    scelta_periodo = st.sidebar.selectbox("Tipo Periodo", ["Tutto lo Storico", "Semestrale", "Mensile", "Annuale"])
    anno_sel = st.sidebar.selectbox("Anno", [str(a) for a in range(datetime.now().year, 2020, -1)])
    
    mese_semestre_sel = ""
    if scelta_periodo == "Mensile":
        mesi_nomi = ["Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno", "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]
        mese_semestre_sel = st.sidebar.selectbox("Mese", mesi_nomi, index=datetime.now().month - 1)
    elif scelta_periodo == "Semestrale":
        mese_semestre_sel = st.sidebar.selectbox("Semestre", ["1° Semestre (Gen-Giu)", "2° Semestre (Lug-Dic)"])

    conn = get_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM fatture ORDER BY data_doc DESC, id DESC")
    righe_db = cur.fetchall()
    cur.close()
    conn.close()

    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Cruscotto & Bilancio", 
        "➕ Nuova Fattura", 
        "📋 Registro & Modifica", 
        "📥 Esporta Excel",
        "📤 Importa Storico"
    ])

    # --- TAB 1: CRUSCOTTO ---
    with tab1:
        sb, sl = calcola_metriche_soci(righe_db, scelta_periodo, anno_sel, mese_semestre_sel)
        
        col1, col2 = st.columns(2)
        for col, socio, dati in [(col1, SOCIO_1, sb), (col2, SOCIO_2, sl)]:
            with col:
                st.subheader(f"👤 Rendiconto: {socio}")
                m1, m2 = st.columns(2)
                m1.metric("💰 Incassi Lordi", f"€ {dati['imp_emesso']:,.2f}")
                m2.metric("📊 Utile Netto", f"€ {dati['utile_netto']:,.2f}")
                
                st.info(
                    f"**Spese Fornitori:** € {dati['imp_ricevuto']:,.2f} | **Dipendenti:** € {dati['costo_dipendenti']:,.2f}\n\n"
                    f"**Note di Credito:** € {dati['nota_credito_storno']:,.2f} | **Omaggi:** € {dati['valore_omaggi']:,.2f}\n\n"
                    f"**IVA Debito:** € {dati['iva_debito']:,.2f} | **IVA Credito:** € {dati['iva_credito']:,.2f}\n\n"
                    f"**Liquidazione IVA ({'DA VERSARE' if dati['iva_bilancio']>=0 else 'A CREDITO'}):** € {abs(dati['iva_bilancio']):,.2f}\n\n"
                    f"**Ritenute Subite:** € {dati['ritenuta_subita']:,.2f} | **Da Versare (F24):** € {dati['ritenuta_da_versare']:,.2f}\n\n"
                    f"💵 **LIQUIDITÀ DI CASSA STIMATA:** € {dati['liquidita_cassa']:,.2f}"
                )

        st.divider()
        st.subheader("👑 Bilancio Provvisorio Combinato Società")
        tot_ricavi = sb["imp_emesso"] + sl["imp_emesso"]
        tot_spese = sb["imp_ricevuto"] + sl["imp_ricevuto"]
        tot_iva = sb["iva_bilancio"] + sl["iva_bilancio"]
        tot_utile = sb["utile_netto"] + sl["utile_netto"]
        tot_cassa = sb["liquidita_cassa"] + sl["liquidita_cassa"]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Fatturato Globale", f"€ {tot_ricavi:,.2f}")
        c2.metric("Spese Globali", f"€ {tot_spese:,.2f}")
        c3.metric("Utile Netto Gruppo", f"€ {tot_utile:,.2f}")
        c4.metric("Liquidità Cassa Gruppo", f"€ {tot_cassa:,.2f}")
        st.caption(f"Equilibrio IVA Aziendale: {'DA VERSARE' if tot_iva >= 0 else 'A CREDITO'} € {abs(tot_iva):,.2f}")

    # --- TAB 2: INSERIMENTO NUOVA FATTURA ---
    with tab2:
        st.subheader("Inserisci Nuovo Documento")
        with st.form("form_nuova_fattura", clear_on_submit=True):
            tipo_doc = st.selectbox("Tipo Documento", ["EMESSA", "RICEVUTA", "OMAGGIO_FORNITORE", "NOTA_CREDITO"])
            socio_doc = st.selectbox("Socio Intestatario", [SOCIO_1, SOCIO_2])
            data_doc = st.date_input("Data Documento", value=datetime.now())
            num_doc = st.text_input("Numero Documento")
            anag_doc = st.text_input("Cliente / Fornitore (Ragione Sociale)")
            imp_doc = st.number_input("Importo Imponibile (€)", min_value=0.0, step=10.0, format="%.2f")
            dip_doc = st.number_input("Di cui Costo Dipendenti (€) - Solo per Fatture Ricevute/Emesse", min_value=0.0, step=10.0, format="%.2f")
            iva_doc = st.selectbox("Aliquota IVA (%)", [22, 10, 4, 0])
            rit_doc = st.selectbox("Ritenuta d'Acconto (%)", [0, 20])

            submitted = st.form_submit_button("💾 Salva nei Registri", use_container_width=True)
            if submitted:
                if not num_doc or not anag_doc:
                    st.error("Inserisci Numero Documento e Ragione Sociale!")
                else:
                    rit_finale = 0 if tipo_doc in ["NOTA_CREDITO", "OMAGGIO_FORNITORE"] else rit_doc
                    dip_finale = 0.0 if tipo_doc in ["NOTA_CREDITO", "OMAGGIO_FORNITORE"] else dip_doc
                    aggiungi_fattura_db(tipo_doc, num_doc, anag_doc, imp_doc, iva_doc, socio_doc, rit_finale, dip_finale, data_doc.strftime("%Y-%m-%d"))
                    st.success(f"Documento {num_doc} salvato con successo!")
                    st.rerun()

    # --- TAB 3: REGISTRO, FILTRI, MODIFICA ED ELIMINAZIONE ---
    with tab3:
        st.subheader("Registro Fatture")
        f_col1, f_col2 = st.columns(2)
        filtro_socio = f_col1.selectbox("Filtra per Socio", ["Tutti i Soci", SOCIO_1, SOCIO_2])
        filtro_testo = f_col2.text_input("Cerca per N° Fattura o Cliente/Fornitore")

        righe_filtrate = []
        tot_filtrato = 0.0
        for r in righe_db:
            if not normalizza_e_controlla_data(r["data_doc"], scelta_periodo, anno_sel, mese_semestre_sel):
                continue
            if filtro_socio != "Tutti i Soci" and r["socio"] != filtro_socio:
                continue
            if filtro_testo and (filtro_testo.lower() not in str(r["num"]).lower() and filtro_testo.lower() not in str(r["anagrafica"]).lower()):
                continue
            righe_filtrate.append(r)
            tot_filtrato += -r["imponibile"] if r["tipo"] == "NOTA_CREDITO" else r["imponibile"]

        st.success(f"**Totale Imponibile Corrente Filtrato ({len(righe_filtrate)} documenti):** € {tot_filtrato:,.2f}")
        
        if righe_filtrate:
            df_vis = pd.DataFrame(righe_filtrate)
            st.dataframe(df_vis[["id", "data_doc", "socio", "tipo", "num", "anagrafica", "imponibile", "costo_dipendenti", "iva_perc", "ritenuta_perc"]], use_container_width=True, hide_index=True)

            with st.expander("✏️ Modifica o Elimina una Fattura"):
                opzioni_id = {f"ID {r['id']} | {r['data_doc']} | N° {r['num']} - {r['anagrafica']} (€{r['imponibile']})": r for r in righe_filtrate}
                scelta_record = st.selectbox("Seleziona documento:", list(opzioni_id.keys()))
                rec = opzioni_id[scelta_record]

                with st.form("form_modifica"):
                    m_data = st.text_input("Data (AAAA-MM-GG)", value=rec["data_doc"])
                    m_num = st.text_input("Numero Documento", value=rec["num"])
                    m_anag = st.text_input("Cliente / Fornitore", value=rec["anagrafica"])
                    m_imp = st.number_input("Imponibile (€)", value=float(rec["imponibile"]), format="%.2f")
                    
                    c_btn1, c_btn2 = st.columns(2)
                    salva_mod = c_btn1.form_submit_button("💾 Aggiorna Dati", use_container_width=True)
                    elimina_mod = c_btn2.form_submit_button("❌ Elimina Documento", type="primary", use_container_width=True)

                    if salva_mod:
                        conn = get_connection()
                        conn.cursor().execute("UPDATE fatture SET data_doc=%s, num=%s, anagrafica=%s, imponibile=%s WHERE id=%s", (m_data, m_num, m_anag, m_imp, rec["id"]))
                        conn.commit()
                        conn.close()
                        st.success("Aggiornato!")
                        st.rerun()

                    if elimina_mod:
                        conn = get_connection()
                        conn.cursor().execute("DELETE FROM fatture WHERE id=%s", (rec["id"],))
                        conn.commit()
                        conn.close()
                        st.warning("Documento eliminato!")
                        st.rerun()
        else:
            st.info("Nessun documento trovato per i filtri selezionati.")

    # --- TAB 4: ESPORTAZIONE EXCEL ---
    with tab4:
        st.subheader("Scarica Report Excel")
        if righe_filtrate:
            df_exp = pd.DataFrame(righe_filtrate)
            df_exp['IVA_EUR'] = df_exp['imponibile'] * (df_exp['iva_perc'] / 100)
            df_exp['Ritenuta_EUR'] = df_exp.apply(lambda r: r['imponibile'] * (r['ritenuta_perc'] / 100) if r['tipo'] not in ['NOTA_CREDITO', 'OMAGGIO_FORNITORE'] else 0.0, axis=1)
            df_exp['Totale_Fattura_EUR'] = df_exp.apply(lambda r: (r['imponibile'] + r['IVA_EUR'] - r['Ritenuta_EUR']) if r['tipo'] != 'NOTA_CREDITO' else -(r['imponibile'] + r['IVA_EUR']), axis=1)
            
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_exp.to_excel(writer, index=False, sheet_name="Registro_Fatture")
            
            st.download_button(
                label="📋 Scarica Registro Fatture (.xlsx)",
                data=buffer.getvalue(),
                file_name=f"registro_soci_{scelta_periodo}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )

    # --- TAB 5: IMPORTAZIONE STORICO DA EXCEL O DB ---
    with tab5:
        st.subheader("📤 Importa Dati dal Vecchio Gestionale")
        st.write("Carica qui il tuo file **`.xlsx`** (es. `registro_individuale_soci.xlsx`) oppure il database **`contabilita_soci.db`** per trasferire tutte le fatture nel database cloud.")
        
        file_caricato = st.file_uploader("Seleziona file Excel (.xlsx) o Database (.db)", type=["xlsx", "db", "sqlite", "sqlite3"])
        svuota_prima = st.checkbox("Svuota il database cloud prima di importare (consigliato per evitare doppioni)", value=True)
        
        if file_caricato is not None:
            if st.button("🚀 Avvia Importazione Completa", type="primary", use_container_width=True):
                try:
                    if file_caricato.name.endswith(".xlsx"):
                        df_imp = pd.read_excel(file_caricato)
                    else:
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
                            tmp.write(file_caricato.getvalue())
                            tmp_path = tmp.name
                        sq_conn = sqlite3.connect(tmp_path)
                        df_imp = pd.read_sql_query("SELECT * FROM fatture", sq_conn)
                        sq_conn.close()
                        os.remove(tmp_path)

                    conn = get_connection()
                    cur = conn.cursor()
                    if svuota_prima:
                        cur.execute("DELETE FROM fatture")

                    count = 0
                    for _, row in df_imp.iterrows():
                        socio_val = str(row.get("socio", "")).strip()
                        if socio_val == "SOCIO B":
                            socio_val = SOCIO_1
                        elif socio_val == "SOCIO L":
                            socio_val = SOCIO_2

                        data_val = str(row.get("data_doc", "")).strip()[:10]
                        tipo_val = str(row.get("tipo", "EMESSA")).strip()
                        num_val = str(row.get("num", "")).strip()
                        anag_val = str(row.get("anagrafica", "")).strip()
                        imp_val = float(row.get("imponibile", 0.0) or 0.0)
                        iva_val = int(row.get("iva_perc", 0) or 0)
                        rit_val = int(row.get("ritenuta_perc", 0) or 0)
                        dip_val = float(row.get("costo_dipendenti", 0.0) or 0.0)

                        cur.execute(
                            """INSERT INTO fatture (tipo, num, anagrafica, imponibile, iva_perc, socio, ritenuta_perc, costo_dipendenti, data_doc) 
                               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                            (tipo_val, num_val, anag_val, imp_val, iva_val, socio_val, rit_val, dip_val, data_val)
                        )
                        count += 1

                    conn.commit()
                    cur.close()
                    conn.close()
                    st.success(f"✅ Importati con successo {count} documenti nel database online!")
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore durante l'importazione: {e}")

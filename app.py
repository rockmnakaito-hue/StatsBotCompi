import streamlit as st
import pandas as pd
from datetime import datetime
from io import BytesIO
import os

# ===============================
#  CONFIG
# ===============================
st.set_page_config(page_title="Bot para sacar STATS de turno", layout="wide")
st.title("Bot para sacar STATS de turno")

# ===============================
#  SIDEBAR: archivos opcionales
# ===============================
st.sidebar.header("⚙️ Opciones adicionales")
st.sidebar.write("Aquí puedes actualizar los archivos base de datos:")

connecteam_file = st.sidebar.file_uploader("Actualizar horario semanal (CSV)", type=["csv"], key="connecteam_up")
mapa_file = st.sidebar.file_uploader("Actualizar traducción de nombres (CSV o XLSX)", type=["csv", "xlsx"], key="mapa_up")

# ===============================
#  CARGA DE BASES DE DATOS (persistentes .pkl)
# ===============================
try:
    df_connecteam = pd.read_pickle("connecteam.pkl")
except FileNotFoundError:
    df_connecteam = pd.DataFrame()

try:
    df_mapa_nombres = pd.read_pickle("mapa_nombres.pkl")
except FileNotFoundError:
    df_mapa_nombres = pd.DataFrame()

# ===============================
#  ACTUALIZAR BASES DE DATOS (al subir en sidebar)
# ===============================
if connecteam_file is not None:
    try:
        df_connecteam = pd.read_csv(connecteam_file)
        if 'Date' in df_connecteam.columns:
            df_connecteam['Date'] = pd.to_datetime(df_connecteam['Date'], errors='coerce', format="%m/%d/%Y")
        df_connecteam.to_pickle("connecteam.pkl")
        st.sidebar.success("Horario semanal actualizado.")
    except Exception as e:
        st.sidebar.error(f"Error al leer Connecteam: {e}")

if mapa_file is not None:
    try:
        fname = mapa_file.name.lower()
        if fname.endswith(".csv"):
            df_mapa_nombres = pd.read_csv(mapa_file)
        else:
            df_mapa_nombres = pd.read_excel(mapa_file)
        df_mapa_nombres.columns = df_mapa_nombres.columns.str.strip()
        df_mapa_nombres.to_pickle("mapa_nombres.pkl")
        st.sidebar.success("Traducción de nombres actualizada.")
    except Exception as e:
        st.sidebar.error(f"Error al leer mapa de nombres: {e}")

# ===============================
#  SELECCIÓN DE ARCHIVO LIVEAGENT (obligatorio)
# ===============================
live_file = st.file_uploader("Sube el CSV exportado de LiveAgent (stats)", type=["csv"], key="live_up")

if live_file is None:
    st.info("Por favor, sube el archivo CSV exportado de LiveAgent para continuar.")
    st.stop()

try:
    df_live = pd.read_csv(live_file)
except Exception as e:
    st.error(f"No se pudo leer el CSV de LiveAgent: {e}")
    st.stop()

df_live.columns = df_live.columns.str.strip()

# ===============================
#  SELECCIÓN DE FECHA (basada en connecteam.pkl)
# ===============================
if df_connecteam.empty:
    st.warning("No hay archivo de Connecteam cargado. Puedes subirlo desde la barra lateral para seleccionar fecha y turnos.")
    selected_date = st.date_input("Fecha a procesar (usar sin Connecteam para generar archivo vacío):", value=datetime.today())
    df_connecteam_day = pd.DataFrame()
else:
    if 'Date' not in df_connecteam.columns:
        st.error("El archivo Connecteam no contiene la columna 'Date'. Sube un CSV con Date, Shift title, Users.")
        st.stop()
    fechas = sorted(pd.to_datetime(df_connecteam['Date'], errors='coerce').dropna().dt.date.unique())
    selected_date = st.selectbox("Selecciona la fecha para generar los stats", fechas)
    df_connecteam['Date'] = pd.to_datetime(df_connecteam['Date'], errors='coerce')
    df_connecteam_day = df_connecteam[df_connecteam['Date'].dt.date == pd.to_datetime(selected_date).date()]

# ===============================
#  CREAR DICCIONARIO DE NOMBRES (mapa)
# ===============================
map_dict = {}
if not df_mapa_nombres.empty:
    df_mapa_nombres.columns = df_mapa_nombres.columns.str.strip()
    for col in ['Nombre', 'Apellido', 'Nombre Live', 'Apellido Live']:
        if col in df_mapa_nombres.columns:
            df_mapa_nombres[col] = df_mapa_nombres[col].astype(str).str.strip().str.title()
    for _, row in df_mapa_nombres.iterrows():
        key = f"{row.get('Nombre', '').strip()} {row.get('Apellido', '').strip()}".strip()
        if key:
            map_dict[key] = (row.get('Nombre Live', '').strip().title(), row.get('Apellido Live', '').strip().title())

# ===============================
#  PROCESAR TURNOS DEL DÍA (crear dfs_turnos inicial)
# ===============================
TIME_COLS = ['Call seconds', 'Outgoing call seconds', 'Tiempo promedio de llamada', 'Tiempo de trabajo']

initial_dfs_turnos = {}
initial_logs = []

if df_connecteam_day.empty:
    # no hay turnos para esa fecha
    initial_dfs_turnos = {}
else:
    df_connecteam_day['Shift title'] = df_connecteam_day['Shift title'].astype(str).str.strip().str.title()
    df_connecteam_day['Users'] = df_connecteam_day['Users'].astype(str)
    turnos = df_connecteam_day['Shift title'].dropna().unique()
    for turno in turnos:
        users_series = df_connecteam_day[df_connecteam_day['Shift title'] == turno]['Users']
        users = []
        for val in users_series:
            if pd.isna(val) or str(val).strip().lower() == 'nan':
                continue
            for u in str(val).split(','):
                u = u.strip().title()
                if u:
                    users.append(u)

        live_names = []
        for u in users:
            if u in map_dict:
                live_names.append(map_dict[u])
            else:
                initial_logs.append(f"⚠️ No se encontró usuario en el mapeo: {u}")
                live_names.append((u, None))

        df_turno = pd.DataFrame()
        if 'First Name' in df_live.columns:
            df_live['First Name'] = df_live['First Name'].astype(str).str.strip().str.title()
        if 'Last Name' in df_live.columns:
            df_live['Last Name'] = df_live['Last Name'].astype(str).str.strip().str.title()

        for first_name, last_name in live_names:
            if last_name:
                df_user = df_live[(df_live['First Name'] == first_name) & (df_live['Last Name'] == last_name)]
            else:
                df_user = df_live[df_live['First Name'] == first_name]

            if df_user.empty:
                initial_logs.append(f"⚠️ Usuario no encontrado en LiveAgent: {first_name} {last_name}")
            else:
                df_turno = pd.concat([df_turno, df_user], ignore_index=True)

        for col in TIME_COLS:
            if col in df_turno.columns:
                try:
                    df_turno[col] = (pd.to_numeric(df_turno[col], errors='coerce') / 60).round(2)
                except Exception as e:
                    initial_logs.append(f"⚠️ Error convirtiendo columna {col} en turno {turno}: {e}")

        initial_dfs_turnos[turno] = df_turno

# ===============================
#  SESSION STATE: persistir entre interacciones
# ===============================
if 'last_selected_date' not in st.session_state or st.session_state['last_selected_date'] != str(selected_date):
    # nueva fecha: inicializar session_state con los dfs_turnos y logs
    st.session_state['dfs_turnos'] = initial_dfs_turnos.copy()
    st.session_state['logs'] = initial_logs.copy()
    st.session_state['last_selected_date'] = str(selected_date)
# A partir de aquí trabajamos con session_state['dfs_turnos'] y ['logs']
dfs_turnos_ss = st.session_state.get('dfs_turnos', {}).copy()
logs_ss = st.session_state.get('logs', []).copy()

# ===============================
# MOSTRAR LOGS Y PREVIEWS (legibles desde session_state)
# ===============================
st.subheader("Logs / Advertencias")
if logs_ss:
    for l in logs_ss:
        st.write(l)
else:
    st.write("No hay advertencias.")

st.markdown("---")
st.subheader("Previews (por turno)")
for turno, df in dfs_turnos_ss.items():
    with st.expander(f"Pestaña: {turno} (rows: {len(df)})", expanded=False):
        if df.empty:
            st.write("_No hay datos para este turno._")
        else:
            st.dataframe(df.head(200))

# ------------------------------
# DETECCIÓN Y ASIGNACIÓN DE "HORAS EXTRA" / AGENTES NO ASIGNADOS
# ------------------------------
st.markdown("---")
st.subheader("Detectar agentes en LiveAgent no asignados a ningún turno (horas extra)")

threshold_minutes = st.number_input("Umbral mínimo de Tiempo de trabajo (minutos) para detectar horas extra", min_value=1, max_value=1440, value=15)

# construir conjunto de asignados desde session_state
assigned_set = set()
for df_ in st.session_state.get('dfs_turnos', {}).values():
    if df_ is None or df_.empty:
        continue
    if 'First Name' in df_.columns and 'Last Name' in df_.columns:
        for _, r in df_.iterrows():
            assigned_set.add(f"{str(r['First Name']).strip().title()} {str(r['Last Name']).strip().title()}".strip())
    elif 'First Name' in df_.columns:
        for _, r in df_.iterrows():
            assigned_set.add(str(r['First Name']).strip().title())

# tiempo trabajado en minutos
if 'Tiempo de trabajo' in df_live.columns:
    df_live['_tiempo_min'] = pd.to_numeric(df_live['Tiempo de trabajo'], errors='coerce') / 60.0
else:
    df_live['_tiempo_min'] = 0.0

# preparar candidatos
candidates_df = df_live.copy()

def make_key(row):
    fn = str(row.get('First Name', '')).strip().title()
    ln = str(row.get('Last Name', '')).strip().title()
    key = f"{fn} {ln}".strip()
    if key == "" or key == " ":
        return None
    return key

candidates_df['_key'] = candidates_df.apply(make_key, axis=1)
candidates_df = candidates_df[candidates_df['_key'].notna()]
candidates_df = candidates_df[~candidates_df['_key'].isin(assigned_set)]
candidates_df = candidates_df[candidates_df['_tiempo_min'] > float(threshold_minutes)]

if candidates_df.empty:
    st.info("No se detectaron agentes no asignados que superen el umbral.")
else:
    st.write(f"Se detectaron {len(candidates_df)} agente(s) no asignado(s) que superan {threshold_minutes} minutos:")
    selectable = [f"{r['_key']} — {r['_tiempo_min']:.1f} min" for _, r in candidates_df.iterrows()]
    selected_items = st.multiselect("Selecciona los agentes que quieres asignar a un turno", options=selectable)

    existing_turnos = list(st.session_state.get('dfs_turnos', {}).keys())
    existing_turnos_sorted = sorted(existing_turnos)
    target_turno = st.selectbox("Selecciona el turno destino (o escribe uno nuevo abajo)", options=["-- Crear nuevo turno --"] + existing_turnos_sorted)

    new_turno_name = None
    if target_turno == "-- Crear nuevo turno --":
        new_turno_name = st.text_input("Nombre del nuevo turno (ej. Jornada Extra)", value="Jornada Extra")
        use_turno = new_turno_name.strip()
    else:
        use_turno = target_turno

    if st.button("Asignar agentes seleccionados al turno"):
        if not selected_items:
            st.warning("Selecciona al menos un agente para asignar.")
        else:
            selected_keys = [s.split(" — ")[0] for s in selected_items]
            # inicializar turno si no existe en session_state
            if use_turno not in st.session_state['dfs_turnos']:
                st.session_state['dfs_turnos'][use_turno] = pd.DataFrame(columns=df_live.columns.tolist())
            # añadir filas y logs
            added = 0
            for k in selected_keys:
                rows = candidates_df[candidates_df['_key'] == k]
                if not rows.empty:
                    rows_to_add = rows.drop(columns=['_tiempo_min','_key'], errors='ignore').copy()
                    st.session_state['dfs_turnos'][use_turno] = pd.concat([st.session_state['dfs_turnos'][use_turno], rows_to_add], ignore_index=True)
                    st.session_state['logs'].append(f"🔁 Asignado {k} al turno {use_turno} (horas extra detectada).")
                    added += len(rows_to_add)
                else:
                    st.session_state['logs'].append(f"⚠️ No se encontró la fila completa para {k} al asignar.")
            st.success(f"{len(selected_keys)} agente(s) asignado(s) a '{use_turno}'. ({added} filas añadidas)")
            # después de asignar, recalc assigned_set y candidates (se forzará rerun y los widgets se actualizan)
            st.experimental_rerun()

# ===============================
#  GENERAR XLSX Y DESCARGA (usa session_state)
# ===============================
def generate_xlsx_bytes(dfs_dict, out_basename="stats_por_turno", date_obj=selected_date):
    bio = BytesIO()
    date_str = pd.to_datetime(date_obj).strftime("%Y-%m-%d")
    fname = f"{out_basename}_{date_str}.xlsx"
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        if dfs_dict:
            for turno, df in dfs_dict.items():
                safe_name = str(turno)[:31]
                if df.empty:
                    cols = df_live.columns.tolist() if not df_live.empty else []
                    empty_df = pd.DataFrame(columns=cols)
                    empty_df.to_excel(writer, sheet_name=safe_name, index=False)
                else:
                    df.to_excel(writer, sheet_name=safe_name, index=False)
        else:
            safe_name = "Todos"
            df_live.to_excel(writer, sheet_name=safe_name[:31], index=False)
    bio.seek(0)
    return fname, bio.getvalue()

st.markdown("---")
if st.button("Generar archivo .xlsx y preparar descarga"):
    # usar dfs_turnos desde session_state
    fname, xbytes = generate_xlsx_bytes(st.session_state.get('dfs_turnos', {}), "stats_por_turno", selected_date)
    st.success(f"Archivo generado: {fname}")
    st.download_button("📥 Descargar XLSX", data=xbytes, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ===============================
#  FIN
# ===============================

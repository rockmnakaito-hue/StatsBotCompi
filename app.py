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

# 🔹 Primero: horario semanal (Connecteam)
connecteam_file = st.sidebar.file_uploader("Actualizar horario semanal (CSV)", type=["csv"], key="connecteam_up")

# 🔹 Segundo: traducción de nombres (CSV o Excel)
mapa_file = st.sidebar.file_uploader("Actualizar traducción de nombres (CSV o XLSX)", type=["csv", "xlsx"], key="mapa_up")

# ===============================
#  CARGA DE BASES DE DATOS (persistentes .pkl)
# ===============================
# Connecteam (persistente)
try:
    df_connecteam = pd.read_pickle("connecteam.pkl")
except FileNotFoundError:
    df_connecteam = pd.DataFrame()

# Mapa de nombres (persistente)
try:
    df_mapa_nombres = pd.read_pickle("mapa_nombres.pkl")
except FileNotFoundError:
    df_mapa_nombres = pd.DataFrame()

# ===============================
#  ACTUALIZAR BASES DE DATOS (al subir en sidebar)
# ===============================
# Actualizar connecteam desde CSV
if connecteam_file is not None:
    try:
        df_connecteam = pd.read_csv(connecteam_file)
        # normalizar y parsear fecha
        if 'Date' in df_connecteam.columns:
            df_connecteam['Date'] = pd.to_datetime(df_connecteam['Date'], errors='coerce', format="%m/%d/%Y")
        df_connecteam.to_pickle("connecteam.pkl")
        st.sidebar.success("Horario semanal actualizado.")
    except Exception as e:
        st.sidebar.error(f"Error al leer Connecteam: {e}")

# Actualizar mapa de nombres desde CSV o XLSX
if mapa_file is not None:
    try:
        fname = mapa_file.name.lower()
        if fname.endswith(".csv"):
            df_mapa_nombres = pd.read_csv(mapa_file)
        else:
            # xlsx
            df_mapa_nombres = pd.read_excel(mapa_file)
        # Normalizar columnas (strip)
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

# Leer live csv
try:
    df_live = pd.read_csv(live_file)
except Exception as e:
    st.error(f"No se pudo leer el CSV de LiveAgent: {e}")
    st.stop()

# Normalizar columnas del Live
df_live.columns = df_live.columns.str.strip()

# ===============================
#  SELECCIÓN DE FECHA (basada en connecteam.pkl)
# ===============================
if df_connecteam.empty:
    st.warning("No hay archivo de Connecteam cargado. Puedes subirlo desde la barra lateral para seleccionar fecha y turnos.")
    selected_date = st.date_input("Fecha a procesar (usar sin Connecteam para generar archivo vacío):", value=datetime.today())
    df_connecteam_day = pd.DataFrame()
else:
    # Asegurarnos de que Date esté en datetime
    if 'Date' not in df_connecteam.columns:
        st.error("El archivo Connecteam no contiene la columna 'Date'. Sube un CSV con Date, Shift title, Users.")
        st.stop()
    # listar fechas disponibles
    fechas = sorted(pd.to_datetime(df_connecteam['Date'], errors='coerce').dropna().dt.date.unique())
    selected_date = st.selectbox("Selecciona la fecha para generar los stats", fechas)
    # filtrar por la fecha seleccionada
    df_connecteam['Date'] = pd.to_datetime(df_connecteam['Date'], errors='coerce')
    df_connecteam_day = df_connecteam[df_connecteam['Date'].dt.date == pd.to_datetime(selected_date).date()]

# ===============================
#  CREAR DICCIONARIO DE NOMBRES (mapa)
# ===============================
map_dict = {}
if not df_mapa_nombres.empty:
    # Normalizar columnas de mapa y valores de texto
    df_mapa_nombres.columns = df_mapa_nombres.columns.str.strip()
    for col in ['Nombre', 'Apellido', 'Nombre Live', 'Apellido Live']:
        if col in df_mapa_nombres.columns:
            df_mapa_nombres[col] = df_mapa_nombres[col].astype(str).str.strip().str.title()
    # Construir diccionario (key: "Nombre Apellido")
    for _, row in df_mapa_nombres.iterrows():
        key = f"{row.get('Nombre', '').strip()} {row.get('Apellido', '').strip()}".strip()
        if key:
            map_dict[key] = (row.get('Nombre Live', '').strip().title(), row.get('Apellido Live', '').strip().title())

# ===============================
#  PROCESAR TURNOS DEL DÍA
# ===============================
# Columnas de tiempo que convertiremos de segundos a minutos
TIME_COLS = ['Call seconds', 'Outgoing call seconds', 'Tiempo promedio de llamada', 'Tiempo de trabajo']

dfs_turnos = {}
logs = []

# Si no hay connecteam para esa fecha, generamos un archivo vacío con la estructura del live (opcional)
if df_connecteam_day.empty:
    st.info("No se encontraron turnos para la fecha seleccionada (o no se cargó Connecteam). Se generará un Excel con hojas según los datos.")
else:
    # normalizar columnas connecteam
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

        # mapear a nombres Live
        live_names = []
        for u in users:
            if u in map_dict:
                live_names.append(map_dict[u])
            else:
                logs.append(f"⚠️ No se encontró usuario en el mapeo: {u}")
                # si no está en el mapa, lo dejamos como nombre único (First Name), sin apellido
                live_names.append((u, None))

        # buscar en df_live
        df_turno = pd.DataFrame()
        # asegurarse de normalizar nombres del live para la búsqueda
        if 'First Name' in df_live.columns:
            df_live['First Name'] = df_live['First Name'].astype(str).str.strip().str.title()
        if 'Last Name' in df_live.columns:
            df_live['Last Name'] = df_live['Last Name'].astype(str).str.strip().str.title()

        for first_name, last_name in live_names:
            if last_name:  # coincidencia completa
                df_user = df_live[(df_live['First Name'] == first_name) & (df_live['Last Name'] == last_name)]
            else:  # coincidencia por First Name solamente
                df_user = df_live[df_live['First Name'] == first_name]

            if df_user.empty:
                logs.append(f"⚠️ Usuario no encontrado en LiveAgent: {first_name} {last_name}")
            else:
                df_turno = pd.concat([df_turno, df_user], ignore_index=True)

        # convertir segundos a minutos
        for col in TIME_COLS:
            if col in df_turno.columns:
                try:
                    df_turno[col] = (pd.to_numeric(df_turno[col], errors='coerce') / 60).round(2)
                except Exception as e:
                    logs.append(f"⚠️ Error convirtiendo columna {col} en turno {turno}: {e}")

        dfs_turnos[turno] = df_turno

# ===============================
# MOSTRAR LOGS Y PREVIEWS
# ===============================
st.subheader("Logs / Advertencias")
if logs:
    for l in logs:
        st.write(l)
else:
    st.write("No hay advertencias.")

st.markdown("---")
st.subheader("Previews (por turno)")
for turno, df in dfs_turnos.items():
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

# Umbral en minutos para considerar a alguien como 'trabajó' ese día
threshold_minutes = st.number_input("Umbral mínimo de Tiempo de trabajo (minutos) para detectar horas extra", min_value=1, max_value=1440, value=15)

# Construir conjunto de nombres ya asignados (First Last) desde dfs_turnos
assigned_set = set()
for df_ in dfs_turnos.values():
    if df_ is None or df_.empty:
        continue
    if 'First Name' in df_.columns and 'Last Name' in df_.columns:
        for _, r in df_.iterrows():
            assigned_set.add(f"{str(r['First Name']).strip().title()} {str(r['Last Name']).strip().title()}".strip())
    elif 'First Name' in df_.columns:
        for _, r in df_.iterrows():
            assigned_set.add(str(r['First Name']).strip().title())

# Preparar campo 'Tiempo de trabajo' en minutos desde df_live
if 'Tiempo de trabajo' in df_live.columns:
    df_live['_tiempo_min'] = pd.to_numeric(df_live['Tiempo de trabajo'], errors='coerce') / 60.0
else:
    df_live['_tiempo_min'] = 0.0

# Crear lista de candidatos: están en live, no están asignados y superan el umbral
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

# Mostrar candidatos (si los hay)
if candidates_df.empty:
    st.info("No se detectaron agentes no asignados que superen el umbral.")
else:
    st.write(f"Se detectaron {len(candidates_df)} agente(s) no asignado(s) que superan {threshold_minutes} minutos:")
    selectable = [f"{r['_key']} — {r['_tiempo_min']:.1f} min" for _, r in candidates_df.iterrows()]
    selected_items = st.multiselect("Selecciona los agentes que quieres asignar a un turno", options=selectable)

    # Lista de turnos actuales para elegir destino
    existing_turnos = list(dfs_turnos.keys())
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
            if use_turno not in dfs_turnos:
                dfs_turnos[use_turno] = pd.DataFrame(columns=df_live.columns.tolist())

            for k in selected_keys:
                rows = candidates_df[candidates_df['_key'] == k]
                if not rows.empty:
                    rows_to_add = rows.drop(columns=['_tiempo_min','_key'], errors='ignore').copy()
                    dfs_turnos[use_turno] = pd.concat([dfs_turnos[use_turno], rows_to_add], ignore_index=True)
                    logs.append(f"🔁 Asignado {k} al turno {use_turno} (horas extra detectada).")
                else:
                    logs.append(f"⚠️ No se encontró la fila completa para {k} al asignar.")
            st.success(f"{len(selected_keys)} agente(s) asignado(s) a '{use_turno}'.")

# ===============================
#  GENERAR XLSX Y DESCARGA
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
    fname, xbytes = generate_xlsx_bytes(dfs_turnos, "stats_por_turno", selected_date)
    st.success(f"Archivo generado: {fname}")
    st.download_button("📥 Descargar XLSX", data=xbytes, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ===============================
#  FIN
# ===============================

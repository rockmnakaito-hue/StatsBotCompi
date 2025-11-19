import streamlit as st
import pandas as pd
from datetime import datetime
import os

# ===============================
#  TÍTULO
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
    st.info("No se encontraron turnos para la fecha seleccionada (o no se cargó Connecteam). Se generará un Excel con hojas vacías según sea necesario.")
    # no hacemos nada, dfs_turnos quedará vacío y al exportar crearemos hojas vacías si quieres
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
#  MOSTRAR LOGS Y PREVIEWS (opcional)
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

# ===============================
#  GENERAR XLSX Y DESCARGA
# ===============================
from io import BytesIO

def generate_xlsx_bytes(dfs_dict, out_basename="stats_por_turno", date_obj=selected_date):
    bio = BytesIO()
    date_str = pd.to_datetime(date_obj).strftime("%Y-%m-%d")
    fname = f"{out_basename}_{date_str}.xlsx"
    with pd.ExcelWriter(bio, engine="openpyxl") as writer:
        if dfs_dict:
            for turno, df in dfs_dict.items():
                safe_name = str(turno)[:31]
                if df.empty:
                    # escribir encabezados del live si es posible
                    cols = df_live.columns.tolist() if not df_live.empty else []
                    empty_df = pd.DataFrame(columns=cols)
                    empty_df.to_excel(writer, sheet_name=safe_name, index=False)
                else:
                    df.to_excel(writer, sheet_name=safe_name, index=False)
        else:
            # si no hay turnos, crear una hoja con todos los live (por defecto)
            safe_name = "Todos"
            df_live.to_excel(writer, sheet_name=safe_name[:31], index=False)
    bio.seek(0)
    return fname, bio.getvalue()

if st.button("Generar archivo .xlsx y preparar descarga"):
    fname, xbytes = generate_xlsx_bytes(dfs_turnos, "stats_por_turno", selected_date)
    st.success(f"Archivo generado: {fname}")
    st.download_button("📥 Descargar XLSX", data=xbytes, file_name=fname, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ===============================
#  FIN
# ===============================

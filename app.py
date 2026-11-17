from datetime import datetime, timedelta
import io
import re
import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Procesador SIRE Compras - SUNAT",
    page_icon="📊",
    layout="wide",
)

st.title("🛠️ Procesador de Propuesta - SIRE Compras (80 Campos)")
st.markdown(
    "Herramienta optimizada para procesar el TXT de compras de SUNAT, aplicar"
    " las reglas de negocio y previsualizar tanto la entrada como la salida."
)

# 1. Carga del archivo TXT del SIRE
uploaded_file = st.file_uploader(
    "Sube el archivo TXT de la Propuesta de Compras (SIRE)", type=["txt"]
)

if uploaded_file is not None:
  try:
    # Extracción del RUC desde el nombre del archivo
    nombre_original = uploaded_file.name
    ruc_extraido = "20000000001"
    match_ruc = re.search(r"(?:LE)?(\d{11})", nombre_original)
    if match_ruc:
      ruc_extraido = match_ruc.group(1)

    # Lectura del TXT con separador pipe (|), omitiendo cabecera original (header=0) y protegiendo ceros
    df = pd.read_csv(
        uploaded_file, sep="|", header=0, dtype=str, encoding="ISO-8859-1"
    )

    total_columnas = len(df.columns)
    total_registros = len(df)
    st.success(
        f"¡Archivo **{nombre_original}** cargado con éxito! RUC:"
        f" **{ruc_extraido}** | Registros: {total_registros:,} | Columnas:"
        f" {total_columnas}"
    )

    # VISTA PREVIA DE LOS DATOS ORIGINALES
    with st.expander("🔍 Ver vista previa de los datos originales", expanded=False):
      ver_todos_orig = st.checkbox("Mostrar todos los registros originales")
      if ver_todos_orig:
        num_filas_orig = total_registros
      else:
        num_filas_orig = st.slider(
            "Cantidad de filas a visualizar (Original):",
            min_value=5,
            max_value=min(total_registros, 1000),
            value=min(total_registros, 10),
        )
      st.dataframe(df.head(num_filas_orig), use_container_width=True)

    st.divider()
    st.subheader("⚙️ Ejecución de Reglas de Negocio")

    if st.button("🚀 Aplicar Reglas de Negocio"):
      df_proc = df.copy()
      total_inicial = len(df_proc)

      # -------------------------------------------------------------
      # REGLA 1: Borrar registros con fecha de emisión anteriores al mes anterior
      # -------------------------------------------------------------
      col_fch_emision = 4  # Campo 5 (Fecha de emisión -> Índice 4)
      if col_fch_emision < len(df_proc.columns):
        fechas = pd.to_datetime(
            df_proc.iloc[:, col_fch_emision], format="%d/%m/%Y", errors="coerce"
        )

        hoy = datetime.now()
        primer_dia_mes_actual = pd.Timestamp(hoy.year, hoy.month, 1)
        mes_anterior_dt = primer_dia_mes_actual - timedelta(days=1)
        primer_dia_mes_anterior = pd.Timestamp(
            mes_anterior_dt.year, mes_anterior_dt.month, 1
        )

        mask_valido = (fechas >= primer_dia_mes_anterior) | fechas.isna()
        df_proc = df_proc[mask_valido]

        st.info(
            f"📋 Regla 1 aplicada: Se eliminaron"
            f" {total_inicial - len(df_proc)} registros anteriores al mes"
            f" anterior ({primer_dia_mes_anterior.strftime('%m/%Y')})."
        )

      # -------------------------------------------------------------
      # REGLA 2: Notas de Crédito (07)
      # -------------------------------------------------------------
      col_tipo_cp = 4
      if col_tipo_cp < len(df_proc.columns):
        nc_mask = df_proc.iloc[:, col_tipo_cp] == "07"
        st.info(
            f"📋 Regla 2 analizada: Se detectaron {nc_mask.sum()} Notas de"
            " Crédito (07)."
        )

      # -------------------------------------------------------------
      # REGLA 3: Si la fecha de vencimiento está vacía, llenar con fecha de emisión (Campo 5 / Índice 4)
      # -------------------------------------------------------------
      col_fch_venc = 5  # Campo 6 (Fecha de vencimiento -> Índice 5)
      if (
          col_fch_venc < len(df_proc.columns)
          and col_fch_emision < len(df_proc.columns)
      ):
        col_venc_data = df_proc.iloc[:, col_fch_venc]
        nulas_venc = (
            col_venc_data.isna()
            | (col_venc_data.str.strip() == "")
            | (col_venc_data == "00/00/0000")
        )
        df_proc.loc[nulas_venc, df_proc.columns[col_fch_venc]] = df_proc.loc[
            nulas_venc, df_proc.columns[col_fch_emision]
        ]
        st.info(
            f"📋 Regla 3 aplicada: Se completaron {nulas_venc.sum()} fechas de"
            " vencimiento vacías utilizando el Campo 5."
        )

      # -------------------------------------------------------------
      # REGLA 4: Columnas monetarias y formateo (Campos 15 al 25 -> Índices 14 al 24)
      # -------------------------------------------------------------
      try:
        for idx in range(14, 20):
          if idx < len(df_proc.columns):
            df_proc.iloc[:, idx] = "0.00"

        if 20 < len(df_proc.columns) and 24 < len(df_proc.columns):
          df_proc.iloc[:, 20] = df_proc.iloc[:, 24]

        for idx in [22, 23]:
          if idx < len(df_proc.columns):
            df_proc.iloc[:, idx] = "0.00"

        for idx in range(14, 25):
          if idx < len(df_proc.columns):
            df_proc.iloc[:, idx] = (
                pd.to_numeric(df_proc.iloc[:, idx], errors="coerce")
                .fillna(0.0)
                .map("{:.2f}".format)
            )

        st.info("📋 Regla 4 aplicada: Formato monetario y columnas 15-25.")
      except Exception as e:
        st.warning(f"Aviso en Regla 4: {e}")

      # -------------------------------------------------------------
      # REGLA 5: Columna 27 (Campo 27 -> Índice 26) - Limpieza de '1'
      # -------------------------------------------------------------
      columna_27_real = 26
      if columna_27_real < len(df_proc.columns):

        def limpiar_uno(val):
          v_str = str(val).strip()
          if v_str in ["1", "1.0", "1.00", "1.000"]:
            return ""
          return val

        df_proc.iloc[:, columna_27_real] = df_proc.iloc[:, columna_27_real].apply(
            limpiar_uno
        )
        st.info(
            "📋 Regla 5 aplicada: Columna 27 (AA) limpiada de valores '1'."
        )

      # -------------------------------------------------------------
      # REGLA 6: Campos 40 y 41 vacíos (Índices 39 y 40)
      # -------------------------------------------------------------
      for idx_vacio in [39, 40]:  # Campo 40 (índice 39) y Campo 41 (índice 40)
        if idx_vacio < len(df_proc.columns):
          df_proc.iloc[:, idx_vacio] = ""

      st.info("📋 Regla 6 aplicada: Campos 40 y 41 dejados vacíos.")

      st.success(
          "✅ ¡Proceso finalizado con éxito manteniendo los 80 campos!"
      )
      st.session_state["df_procesado"] = df_proc

    # 2. Sección de Descarga y Vista Previa de Salida
    if "df_procesado" in st.session_state:
      st.divider()
      st.subheader("📥 Exportar y Previsualizar Archivo de Reemplazo")

      df_final = st.session_state["df_procesado"]
      total_final_registros = len(df_final)

      st.write(
          f"Registros listos para exportar: **{total_final_registros:,}** | Total"
          f" columnas: **{len(df_final.columns)}**"
      )

      # VISTA PREVIA DEL ARCHIVO DE SALIDA (PROCESADO)
      with st.expander(
          "🔍 Ver vista previa del archivo de salida (Procesado)", expanded=True
      ):
        ver_todos_proc = st.checkbox(
            "Mostrar todos los registros procesados en pantalla"
        )
        if ver_todos_proc:
          num_filas_proc = total_final_registros
        else:
          num_filas_proc = st.slider(
              "Cantidad de filas a visualizar (Salida):",
              min_value=5,
              max_value=min(total_final_registros, 1000),
              value=min(total_final_registros, 10),
          )
        st.dataframe(df_final.head(num_filas_proc), use_container_width=True)

      # Nomenclatura automática (Mes anterior)
      hoy = datetime.now()
      primer_dia_mes_actual = hoy.replace(day=1)
      mes_anterior = primer_dia_mes_actual - timedelta(days=1)
      anio_ant = mes_anterior.strftime("%Y")
      mes_ant = mes_anterior.strftime("%m")

      col_nom1, col_nom2 = st.columns(2)
      with col_nom1:
        ruc_empresa = st.text_input("RUC de la Empresa:", value=ruc_extraido)
      with col_nom2:
        indicador_final = st.text_input(
            "Sufijo / Indicadores finales:", value="021112"
        )

      nombre_generado = (
          f"LE{ruc_empresa}{anio_ant}{mes_ant}00080400{indicador_final}.txt"
      )
      nombre_salida = st.text_input(
          "Nombre final del archivo TXT:", value=nombre_generado
      )

      # Exportar estrictamente SIN ENCABEZADOS
      output = io.StringIO()
      df_final.to_csv(output, sep="|", index=False, header=False)
      txt_bytes = output.getvalue().encode("ISO-8859-1")

      st.download_button(
          label="📥 Descargar TXT Limpio (Sin Encabezados - 80 Campos)",
          data=txt_bytes,
          file_name=nombre_salida,
          mime="text/plain",
      )

  except Exception as e:
    st.error(f"❌ Error al procesar el archivo: {e}")
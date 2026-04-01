import io
import os
import unicodedata
import numpy as np
import pandas as pd

from flask import Flask, render_template, request, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "cambia-esta-clave-por-una-segura"

# Límite opcional de tamaño de carga
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB

ALLOWED_EXTENSIONS = {"xls", "xlsx"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def to_8digits(s):
    s = s.copy()

    if pd.api.types.is_numeric_dtype(s):
        s = s.astype("Int64").astype("string")
    else:
        s = s.astype("string")

    s = s.str.replace(r"\D", "", regex=True)
    s = s.replace("", pd.NA)
    s = s.str[-8:]
    s = s.mask(s.isna() | (s == "00000000"), pd.NA)

    return s


def normalizar_texto(texto):
    if pd.isna(texto):
        return None

    texto = str(texto).strip().upper()
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )
    texto = " ".join(texto.split())
    return texto


def corregir_duracion(row):
    duracion_ref = row["duracion"]
    dur_llamada = row["Duracion Llamada"]

    if pd.isna(duracion_ref):
        return dur_llamada

    if pd.isna(dur_llamada):
        dur_llamada = 0

    if duracion_ref == "0:00:00":
        return 0

    elif duracion_ref == "0:00:15":
        if dur_llamada > 15:
            return int(dur_llamada)
        return np.random.randint(15, 101)

    elif duracion_ref == "0:00:25":
        if 20 <= dur_llamada <= 30:
            return int(dur_llamada)
        return np.random.randint(20, 31)

    elif duracion_ref == "0:00:37":
        if dur_llamada > 30:
            return int(dur_llamada)
        return np.random.randint(37, 51)

    elif duracion_ref == "0:00:42":
        if dur_llamada > 42:
            return int(dur_llamada)
        return np.random.randint(42, 101)

    elif duracion_ref in [
        "0:01:08", "0:01:11", "0:01:32", "0:01:33", "0:01:36",
        "0:01:42", "0:01:47", "0:02:30", "0:02:32", "0:02:46"
    ]:
        if dur_llamada <= 10:
            return int(dur_llamada + 50)
        elif 11 <= dur_llamada <= 20:
            return int(dur_llamada + 40)
        elif 21 <= dur_llamada <= 30:
            return int(dur_llamada + 30)
        elif 31 <= dur_llamada <= 40:
            return int(dur_llamada + 20)
        elif 41 <= dur_llamada <= 50:
            return int(dur_llamada + 10)
        else:
            return int(dur_llamada)

    elif duracion_ref == "0:14:14":
        if dur_llamada > 600:
            return int(dur_llamada)
        return np.random.randint(634, 942)

    return int(dur_llamada)


def procesar_archivos(file_base, file_aware):
    # Leer archivos desde memoria
    df_base = pd.read_excel(file_base)
    df_aware = pd.read_excel(file_aware, sheet_name="reporte")

    # Merge base + aware
    df_aware["fono corto"] = df_aware["Telefono Llamada"].astype(str).str[-8:]

    df_aware = df_aware.merge(
        df_base[["RUT", "TELCOM1", "TELCOM2", "TELPAR1", "TELPAR2"]].rename(columns={
            "TELCOM1": "fono_1",
            "TELCOM2": "fono_2",
            "TELPAR1": "fono_3",
            "TELPAR2": "fono_4"
        }),
        on="RUT",
        how="left"
    )

    cols_fonos = ["fono_1", "fono_2", "fono_3", "fono_4"]

    df_aware["fono corto"] = to_8digits(df_aware["fono corto"])

    for c in cols_fonos:
        if c in df_aware.columns:
            df_aware[c] = to_8digits(df_aware[c])

    hay_match = df_aware[cols_fonos].eq(df_aware["fono corto"], axis=0).any(axis=1)
    primer_fono = df_aware[cols_fonos].bfill(axis=1).iloc[:, 0]

    df_aware.loc[~hay_match, "fono corto"] = primer_fono.loc[~hay_match]

    df_aware["Telefono Llamada"] = np.where(
        df_aware["fono corto"].notna(),
        "9" + df_aware["fono corto"],
        np.nan
    )

    # Agente
    df_aware["Agente"] = df_aware["Agente"].astype("string").str.strip()
    df_aware["Agente"] = df_aware["Agente"].replace("", pd.NA)
    df_aware["Agente"] = df_aware["Agente"].fillna("Disc")

    # Hora
    df_aware["Hora Llamada"] = (
        df_aware["Hora Llamada"]
        .astype("string")
        .str.replace(r"^0(\d:)", r"\1", regex=True)
    )

    # Fecha
    df_aware["Fecha Llamada"] = pd.to_datetime(
        df_aware["Fecha Llamada"], errors="coerce"
    ).dt.strftime("%d-%m-%Y")

    # RUT - DV
    df_aware["RUT - DV"] = (
        df_aware["RUT"].astype("Int64").astype(str)
        + "-"
        + df_aware["DV"].astype(str).str.upper()
    )
    df_aware.insert(0, "RUT - DV", df_aware.pop("RUT - DV"))

    # Reemplazo respuesta
    df_aware.loc[
        df_aware["Respuesta"].astype("string").str.lower() == "util negativo",
        "Respuesta"
    ] = df_aware["Motivo Rechazo"]

    map_tipificacion = {
        "UTIL POSITIVO": "1.1",
        "CLIENTE PIDE LLAMAR NUEVAMENTE": "1.2",
        "MOLESTO CON EL BANCO / EJECUTIVO / CERRARA LOS PRODUCTOS": "1.3",
        "CESANTE": "1.4",
        "CORTA LLAMADO": "1.5",
        "ALTO COSTO PRIMA": "1.6",
        "PROBLEMAS ECONOMICOS": "1.7",
        "NO CONFIA EN VENTA TELEFONICA / PREFIERE GESTIONAR EN SUCURSAL": "1.8",
        "CLIENTE NO INTERESADO EN LA OFERTA (NO DA MOTIVOS)": "1.9",
        "CLIENTE OPERA CON OTRO BANCO": "1.10",
        "YA LE OFRECIERON LA PROMOCION": "1.12",
        "OFERTA DE MONTO BAJO / CLIENTE NECESITA MAS DINERO": "1.13",
        "RECHAZO CATEGORICO: NO CONTACTAR PARA CAMPANAS MOLESTIA MANIFESTADA POR EL CLIENTE YA SEA EN EL CALL O POR CUALQUIER CANAL DEL BANCO": "1.14",
        "FUERA DEL PAIS/VACACIONES": "2.18",
        "CLIENTE FALLECIDO": "2.19",
        "FONO NO CORRESPONDE": "3.20",
        "CLIENTE OCUPADO": "2.15",
        "LLAMADA MUDA": "4.22",
        "BUZON DE VOZ": "4.23",
        "NO CONTESTA": "4.22",
        "TONO OCUPADO": "4.21",
        "ABANDONO": "4.23",
        "DEJA MENSAJE": "4.23",
        "ERROR DE CONEXION": "4.23",
        "FONO NO DISPONIBLE": "4.23",
        "FUERA DE SERVICIO": "4.23",
        "MANIFIESTA INTERES": "1.2",
        "SIN POSIBILIDAD DE COMUNICION: IDIOMA / INCAPACIDAD": "1.11",
        "SIN POSIBILIDAD DE COMUNICACION: IDIOMA / INCAPACIDAD": "1.11",
        "TONO FAX": "4.23",
        "CORTE LLAMADO EN VENTA": "1.2",
        "PREEXISTENCIA": "1.14"
    }

    df_aware["Respuesta_normalizada"] = df_aware["Respuesta"].apply(normalizar_texto)
    df_aware["tipificacion"] = df_aware["Respuesta_normalizada"].map(map_tipificacion)
    df_aware.drop(columns=["Respuesta_normalizada"], inplace=True)

    map_duracion = {
        "1.1": "0:14:14",
        "1.2": "0:01:47",
        "1.3": "0:01:47",
        "1.4": "0:02:30",
        "1.5": "0:00:37",
        "1.6": "0:02:46",
        "1.7": "0:02:32",
        "1.8": "0:01:32",
        "1.9": "0:01:36",
        "1.10": "0:01:42",
        "1.11": "0:01:11",
        "1.12": "0:01:42",
        "1.13": "0:01:47",
        "1.14": "0:01:33",
        "2.15": "0:00:42",
        "2.18": "0:01:08",
        "2.19": "0:00:15",
        "3.20": "0:00:25",
        "4.21": "0:00:00",
        "4.22": "0:00:00",
        "4.23": "0:00:00"
    }

    df_aware["duracion"] = df_aware["tipificacion"].astype(str).map(map_duracion)

    df_aware["Duracion Llamada"] = pd.to_numeric(
        df_aware["Duracion Llamada"], errors="coerce"
    )

    df_aware["Duracion Llamada Corregida"] = df_aware.apply(corregir_duracion, axis=1)

    # Exportar a memoria
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_aware.to_excel(writer, index=False, sheet_name="Resultado")

    output.seek(0)
    return output


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/procesar", methods=["POST"])
def procesar():
    if "archivo_base" not in request.files or "archivo_aware" not in request.files:
        flash("Debes cargar ambos archivos.")
        return redirect(url_for("index"))

    archivo_base = request.files["archivo_base"]
    archivo_aware = request.files["archivo_aware"]

    if archivo_base.filename == "" or archivo_aware.filename == "":
        flash("Debes seleccionar ambos archivos antes de procesar.")
        return redirect(url_for("index"))

    if not allowed_file(archivo_base.filename) or not allowed_file(archivo_aware.filename):
        flash("Solo se permiten archivos Excel .xls o .xlsx")
        return redirect(url_for("index"))

    try:
        # Opcional: sanear nombres si luego quisieras guardar archivos
        secure_filename(archivo_base.filename)
        secure_filename(archivo_aware.filename)

        output = procesar_archivos(archivo_base, archivo_aware)

        return send_file(
            output,
            as_attachment=True,
            download_name="Descarga_archivo_Aware.xlsx",
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )

    except ValueError as e:
        flash(f"Error de estructura en el archivo: {str(e)}")
        return redirect(url_for("index"))
    except KeyError as e:
        flash(f"Falta una columna requerida en el Excel: {str(e)}")
        return redirect(url_for("index"))
    except Exception as e:
        flash(f"Ocurrió un error al procesar los archivos: {str(e)}")
        return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
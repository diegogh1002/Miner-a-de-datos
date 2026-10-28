"""
Práctica 01 - Delitos financieros CDMX 2023
Descarga Carpetas FGJ y Víctimas FGJ por la API CKAN del Portal de Datos Abiertos CDMX,
calcula los resultados del punto 9 y deja CSV listos para Tableau en ./salida/

Uso:
    pip install ckanapi pandas requests
    python fgj_practica01.py
"""
import io
import json
import os
import re
import unicodedata

import pandas as pd
import requests
from ckanapi import RemoteCKAN

ANIO = 2023
PORTAL = "https://datos.cdmx.gob.mx/"
PAQ_CARPETAS = "carpetas-de-investigacion-fgj-de-la-ciudad-de-mexico"
PAQ_VICTIMAS = "victimas-en-carpetas-de-investigacion-fgj"
OUT = "salida"
os.makedirs(OUT, exist_ok=True)

PATRON_FIN = r"(FRAUDE|EXTORSI|CUENTAHABIENTE|ABUSO DE CONFIANZA|FALSIFICACI|DOCUMENTO FALSO|USURPACI|TARJETA)"

# Censo de Población y Vivienda 2020, INEGI (población total por alcaldía)
POBLACION_2020 = {
    "ALVARO OBREGON": 759137, "AZCAPOTZALCO": 432205, "BENITO JUAREZ": 434153,
    "COYOACAN": 614447, "CUAJIMALPA DE MORELOS": 217686, "CUAUHTEMOC": 545884,
    "GUSTAVO A. MADERO": 1173351, "IZTACALCO": 404695, "IZTAPALAPA": 1835486,
    "LA MAGDALENA CONTRERAS": 247622, "MIGUEL HIDALGO": 414470, "MILPA ALTA": 152685,
    "TLAHUAC": 392313, "TLALPAN": 699928, "VENUSTIANO CARRANZA": 443704, "XOCHIMILCO": 442178,
}
ALIAS = {"CUAJIMALPA": "CUAJIMALPA DE MORELOS", "MAGDALENA CONTRERAS": "LA MAGDALENA CONTRERAS",
         "GUSTAVO A MADERO": "GUSTAVO A. MADERO"}


def norm(s):
    if pd.isna(s):
        return s
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().upper().strip()
    s = re.sub(r"\s+", " ", s)
    return ALIAS.get(s, s)


def elegir_recurso(paquete, anio):
    pkg = RemoteCKAN(PORTAL).action.package_show(id=paquete)
    csvs = [r for r in pkg["resources"] if (r.get("format") or "").upper() == "CSV"]
    print(f"\nRecursos CSV en {paquete}:")
    for r in csvs:
        print("  -", r["name"], "|", r["id"])
    anuales = [r for r in csvs if str(anio) in r["name"] and "acumulad" not in r["name"].lower()]
    acumulados = [r for r in csvs if "acumulad" in r["name"].lower()]
    r = (anuales or acumulados or csvs)[0]
    print("  => usando:", r["name"])
    return r


def descargar(recurso):
    print("Descargando", recurso["url"])
    resp = requests.get(recurso["url"], timeout=600)
    resp.raise_for_status()
    return pd.read_csv(io.BytesIO(resp.content), low_memory=False, encoding="utf-8")


def col(df, *opciones):
    mapa = {c.lower(): c for c in df.columns}
    for o in opciones:
        if o in mapa:
            return mapa[o]
    return None


resumen = {}

# ---------------- CARPETAS ----------------
rec_c = elegir_recurso(PAQ_CARPETAS, ANIO)
car = descargar(rec_c)
c_anio = col(car, "anio_hecho", "ao_hechos")
c_fecha = col(car, "fecha_hecho", "fecha_hechos")
c_hora = col(car, "hora_hecho", "hora_hechos")
c_fini = col(car, "fecha_inicio")
c_alc = col(car, "alcaldia_catalogo", "alcaldia_hecho", "alcaldia_hechos")
car = car[pd.to_numeric(car[c_anio], errors="coerce") == ANIO].copy()

resumen["carpetas_total_registros"] = int(len(car))
resumen["carpetas_columnas"] = int(car.shape[1])

car["es_financiero"] = car["delito"].astype(str).str.upper().str.contains(PATRON_FIN, regex=True).astype(int)
car["alcaldia_norm"] = car[c_alc].map(norm)
car["fecha_hecho_dt"] = pd.to_datetime(car[c_fecha], errors="coerce")
car["fecha_inicio_dt"] = pd.to_datetime(car[c_fini], errors="coerce")
car["mes"] = car["fecha_hecho_dt"].dt.month
car["dia_semana"] = car["fecha_hecho_dt"].dt.dayofweek  # 0 = lunes
car["hora"] = pd.to_datetime(car[c_hora], format="%H:%M:%S", errors="coerce").dt.hour
car["hora_desconocida"] = car[c_hora].astype(str).str.startswith("00:00").astype(int)
car["rezago_dias"] = (car["fecha_inicio_dt"] - car["fecha_hecho_dt"]).dt.days

fin = car[car["es_financiero"] == 1].copy()
resumen["carpetas_financieras"] = int(len(fin))
resumen["pct_financieras"] = round(100 * len(fin) / len(car), 2)

# a) distribución temática
por_delito = fin["delito"].value_counts().rename_axis("delito").reset_index(name="carpetas")
por_delito.to_csv(f"{OUT}/a_por_delito.csv", index=False)

# a) por alcaldía + tasa (caso de estudio, punto 6)
por_alc = fin["alcaldia_norm"].value_counts().rename_axis("alcaldia").reset_index(name="carpetas")
por_alc["poblacion_2020"] = por_alc["alcaldia"].map(POBLACION_2020)
por_alc["tasa_100k"] = (por_alc["carpetas"] / por_alc["poblacion_2020"] * 100000).round(1)
por_alc.sort_values("tasa_100k", ascending=False).to_csv(f"{OUT}/a_por_alcaldia_tasa.csv", index=False)

# b) distribución temporal
fin.groupby("mes").size().rename("carpetas").to_csv(f"{OUT}/b_por_mes.csv")
fin[fin["hora_desconocida"] == 0].pivot_table(index="dia_semana", columns="hora", values="delito",
                                               aggfunc="count", fill_value=0).to_csv(f"{OUT}/b_dia_x_hora.csv")

# c) calidad
calidad = pd.DataFrame({
    "nulos": car.isna().sum(),
    "pct_nulos": (100 * car.isna().mean()).round(2),
})
calidad.to_csv(f"{OUT}/c_calidad_nulos_carpetas.csv")
resumen["carpetas_hora_00_00"] = int(car["hora_desconocida"].sum())
resumen["carpetas_sin_coordenadas"] = int(car[col(car, "latitud")].isna().sum())
resumen["carpetas_alcaldia_fuera_de_16"] = int((~car["alcaldia_norm"].isin(POBLACION_2020)).sum())
resumen["carpetas_duplicadas_exactas"] = int(car.duplicated().sum())
resumen["rezago_mediana_dias_financieros"] = float(fin["rezago_dias"].median())

# Extracto para Tableau
fin.drop(columns=["fecha_hecho_dt", "fecha_inicio_dt"]).to_csv(f"{OUT}/tableau_carpetas_financieras_{ANIO}.csv", index=False)

# ---------------- VÍCTIMAS ----------------
try:
    rec_v = elegir_recurso(PAQ_VICTIMAS, ANIO)
    vic = descargar(rec_v)
    v_anio = col(vic, "anio_hecho", "ao_hechos", "anio_inicio")
    vic = vic[pd.to_numeric(vic[v_anio], errors="coerce") == ANIO].copy()
    resumen["victimas_total_registros"] = int(len(vic))
    resumen["victimas_columnas"] = int(vic.shape[1])
    v_del = col(vic, "delito")
    vf = vic[vic[v_del].astype(str).str.upper().str.contains(PATRON_FIN, regex=True)].copy()
    resumen["victimas_financieras"] = int(len(vf))
    v_sexo, v_edad = col(vic, "sexo"), col(vic, "edad")
    edad = pd.to_numeric(vf[v_edad], errors="coerce")
    vf["grupo_edad"] = pd.cut(edad, [-1, 17, 29, 44, 59, 100], labels=["0-17", "18-29", "30-44", "45-59", "60+"])
    vf.groupby([v_sexo, "grupo_edad"], observed=False).size().rename("victimas").to_csv(f"{OUT}/a_victimas_sexo_edad.csv")
    resumen["victimas_edad_nula_o_invalida"] = int(vf["grupo_edad"].isna().sum())
    vf.to_csv(f"{OUT}/tableau_victimas_financieras_{ANIO}.csv", index=False)
except Exception as e:  # el resto del análisis no depende de víctimas
    print("Víctimas no procesadas:", e)

with open(f"{OUT}/resumen.json", "w", encoding="utf-8") as f:
    json.dump(resumen, f, ensure_ascii=False, indent=2)

print("\n===== RESUMEN (pega esto en el chat) =====")
print(json.dumps(resumen, ensure_ascii=False, indent=2))
print("\nTop delitos financieros:\n", por_delito.head(8).to_string(index=False))
print("\nTop alcaldías por tasa:\n", por_alc.sort_values('tasa_100k', ascending=False).head(16).to_string(index=False))
print("\nPor mes:\n", fin.groupby('mes').size().to_string())
print(f"\nArchivos en ./{OUT}/")


#""""""
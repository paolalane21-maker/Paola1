from flask import Flask, render_template, request, jsonify, session, redirect, url_for # type: ignore
import math
import datetime
import sqlite3
import os
import json
from dataclasses import dataclass, field
from typing import Literal
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')

# Database setup
DB_PATH = "users.db"
DATA_DIR = "user_data"

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

def init_db():
    """Inicializa la base de datos de usuarios"""
    if not os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('''CREATE TABLE users
                     (id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT)''')
        conn.commit()
        conn.close()

def login_required(f):
    """Decorador para proteger rutas"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "No autenticado"}), 401
        return f(*args, **kwargs)
    return decorated_function

def get_user_db_path(user_id):
    """Obtiene la ruta de la base de datos del usuario"""
    return os.path.join(DATA_DIR, f"user_{user_id}.db")

def init_user_db(user_id):
    """Inicializa la base de datos personal del usuario"""
    db_path = get_user_db_path(user_id)
    if not os.path.exists(db_path):
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        c.execute('''CREATE TABLE asignaturas
                     (id INTEGER PRIMARY KEY, codigo TEXT, nombre TEXT, creditos REAL, 
                      calificacion TEXT, semestre TEXT)''')
        c.execute('''CREATE TABLE planes_fpf
                     (id INTEGER PRIMARY KEY, periodo TEXT, año INTEGER, num_cuatrimestres INTEGER, 
                      fecha_creacion TEXT)''')
        conn.commit()
        conn.close()

init_db()

# ─────────────────────────────────────────────────────
# LÓGICA ACADÉMICA
# ─────────────────────────────────────────────────────
EQUIVALENCIAS = {"A": 4.0, "B": 3.0, "C": 2.0, "D": 1.0, "F": 0.0, "RET": 0.0}

PERIODOS = [
   "Enero–Abril", "Mayo-Agosto", "Septiembre–Diciembre"
]


TARIFAS = {
    "Monitor": 300,
    "Asistente / Auxiliar": 450,
    "Adscrito": 605,
    "Adjunto": 665,
    "Titular": 730,
    "Inglés / Postgrado Odontología": 900,
    "Talleres EG": 600,
    "Maestrías": 1100,
}


def redondear(valor, politica):
    if politica == "Round": return round(valor)
    if politica == "Ceil":  return math.ceil(valor)
    if politica == "Floor": return math.floor(valor)
    return valor


def convertir_calificacion(letra):
    key = letra.strip().upper()
    if key not in EQUIVALENCIAS:
        raise ValueError(f"Calificación '{letra}' no válida.")
    return EQUIVALENCIAS[key]


def _normalizar_lista(items):
    resultado = []
    for item in items:
        if isinstance(item, dict):
            resultado.append({
                "codigo": item.get("codigo", "N/A"),
                "nombre": item.get("nombre", ""),
                "creditos": float(item["creditos"]),
                "calificacion": str(item["calificacion"]).strip().upper(),
                "semestre": item.get("semestre", ""),
            })
    return resultado


def _aplicar_modo_repeticion(asignaturas, modo):
    if modo == "acumular":
        return asignaturas
    mapa = {}
    for a in asignaturas:
        mapa[a["codigo"]] = a
    return list(mapa.values())


def calcular_indice_acumulado(historial, modo_repeticion="reemplazar"):
    if not historial:
        raise ValueError("El historial está vacío.")
    todas = []
    for sem in historial:
        todas.extend(_normalizar_lista(sem))
    procesadas = _aplicar_modo_repeticion(todas, modo_repeticion)
    tc = sum(a["creditos"] for a in procesadas)
    tp = sum(a["creditos"] * convertir_calificacion(a["calificacion"]) for a in procesadas)
    if tc == 0:
        raise ZeroDivisionError("Total de créditos es 0.")
    ia = round(tp / tc, 2)

    ultimo_sem = _normalizar_lista(historial[-1])
    ultimo_proc = _aplicar_modo_repeticion(ultimo_sem, modo_repeticion)
    tc_sem = sum(a["creditos"] for a in ultimo_proc)
    tp_sem = sum(a["creditos"] * convertir_calificacion(a["calificacion"]) for a in ultimo_proc)
    is_ = round(tp_sem / tc_sem, 2) if tc_sem > 0 else 0

    detalle = [{
        "codigo": a["codigo"], "nombre": a["nombre"],
        "creditos": a["creditos"], "calificacion": a["calificacion"],
        "valor": convertir_calificacion(a["calificacion"]),
        "puntos": round(a["creditos"] * convertir_calificacion(a["calificacion"]), 2)
    } for a in ultimo_proc]

    return {
        "indice_semestral": is_,
        "indice_acumulado": ia,
        "total_creditos": tc,
        "total_puntos": round(tp, 2),
        "detalle": detalle,
    }


def _reconstruir_historial(filas):
    orden = []
    grupos = {}
    for f in filas:
        s = f["semestre"]
        if s not in grupos:
            orden.append(s)
            grupos[s] = []
        grupos[s].append(f)
    return [grupos[s] for s in orden]


def calcular_horas(creditos, tipo):
    if tipo == "Tutoría": return int(creditos * 10)
    elif tipo == "Curso Especial": return int(creditos * 15)
    else: raise ValueError("Tipo no válido")


def calcular_costo_total(tarifa, horas):
    return (tarifa * horas) * 2


def calcular_horas_creditos(ht, hp, hi, semanas, politica="Round"):
    """Calcula créditos a partir de horas teóricas, prácticas e investigación."""
    if semanas <= 0:
        raise ValueError("El número de semanas debe ser mayor a 0.")
    total_horas = ht + hp + hi
    ht_sem = ht / semanas
    hp_sem = hp / semanas
    hi_sem = hi / semanas
    cred_ht = ht / 15
    cred_hp = hp / 30
    cred_hi = hi / 45
    total_cred = cred_ht + cred_hp + cred_hi
    total_redondeado = redondear(total_cred, politica)
    return {
        "horas_totales": {"ht": ht, "hp": hp, "hi": hi, "total": total_horas},
        "horas_semanales": {
            "ht": round(ht_sem, 2),
            "hp": round(hp_sem, 2),
            "hi": round(hi_sem, 2),
        },
        "creditos": {
            "ht": round(cred_ht, 2),
            "hp": round(cred_hp, 2),
            "hi": round(cred_hi, 2),
            "total": round(total_cred, 2),
            "redondeado": total_redondeado,
        },
        "semanas": semanas,
        "politica": politica,
    }


def _siguiente_periodo(per, año):
    idx = PERIODOS.index(per)
    if idx + 1 < len(PERIODOS):
        return PERIODOS[idx + 1], año
    return PERIODOS[0], año + 1


def generar_calendario_auto(desde, hasta, overrides=None):
    if overrides is None: overrides = {}
    cal = {}
    for año in range(desde, hasta + 1):
        cal[año] = {}
        for idx, per in enumerate(PERIODOS):
            if (año, per) in overrides:
                cal[año][per] = overrides[(año, per)]
            else:
                # Enero-Abril (idx=0): meses 1-4
                # Mayo-Agosto (idx=1): meses 5-8
                # Septiembre-Diciembre (idx=2): meses 9-12
                mes_ini = idx * 4 + 1
                mes_fin = (idx + 1) * 4
                try:
                    fi = datetime.date(año, mes_ini, 1)
                    ff = datetime.date(año, mes_fin, 28) if mes_fin == 2 else datetime.date(año, mes_fin, 30) if mes_fin in [4,6,9,11] else datetime.date(año, mes_fin, 31)
                    if ff > fi:
                        cal[año][per] = (fi, ff)
                except:
                    pass
    return cal


def generar_plan_fpf(periodo_inicio, año_inicio, num_cuatrimestres, calendario):
    hoy = datetime.date.today()
    plan = []
    per, año = periodo_inicio, año_inicio
    for i in range(num_cuatrimestres):
        fi = ff = None
        if año in calendario and per in calendario[año]:
            fi, ff = calendario[año][per]
        if fi and ff:
            if hoy > ff: estado = "completado"
            elif fi <= hoy <= ff: estado = "activo"
            else: estado = "futuro"
        else:
            estado = "sin_fecha"
        plan.append({
            "numero": i + 1, "periodo": per, "año": año,
            "fecha_inicio": fi.isoformat() if fi else None,
            "fecha_fin": ff.isoformat() if ff else None,
            "estado": estado,
        })
        per, año = _siguiente_periodo(per, año)
    return plan


# ─────────────────────────────────────────────────────
# CALCULADORA ACADÉMICA
# ─────────────────────────────────────────────────────
def calcular_notas(notas, semanas, politica):
    if not notas:
        raise ValueError("Lista de notas vacía.")
    pesos = {"primer_parcial": 0.25, "segundo_parcial": 0.25, "practicas": 0.10, "final": 0.40}
    if len(notas) != 4:
        raise ValueError("Se necesitan 4 notas: Parcial 1, Parcial 2, Prácticas, Final.")
    p1, p2, prac, fin = notas
    definitiva = p1 * 0.25 + p2 * 0.25 + prac * 0.10 + fin * 0.40
    if definitiva >= 60:
        aprobado = True
        letra = "A" if definitiva >= 90 else "B" if definitiva >= 80 else "C" if definitiva >= 70 else "D"
    else:
        aprobado = False
        letra = "F"
    return {
        "definitiva": round(definitiva, 2),
        "aprobado": aprobado,
        "letra": letra,
        "desglose": {
            "primer_parcial": round(p1 * 0.25, 2),
            "segundo_parcial": round(p2 * 0.25, 2),
            "practicas": round(prac * 0.10, 2),
            "final": round(fin * 0.40, 2),
        }
    }


# ─────────────────────────────────────────────────────
# RUTAS - AUTENTICACIÓN
# ─────────────────────────────────────────────────────
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")
    
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    
    if not username or not password:
        return jsonify({"error": "Usuario y contraseña requeridos"}), 400
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, password FROM users WHERE username = ?", (username,))
    user = c.fetchone()
    conn.close()
    
    if user and user[1] == password:  # En producción, usar hash
        session['user_id'] = user[0]
        session['username'] = username
        init_user_db(user[0])
        return jsonify({"success": True, "message": "Login exitoso"})
    
    return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    password_confirm = data.get("password_confirm", "").strip()
    
    if not username or not password:
        return jsonify({"error": "Usuario y contraseña requeridos"}), 400
    
    if password != password_confirm:
        return jsonify({"error": "Las contraseñas no coinciden"}), 400
    
    if len(password) < 6:
        return jsonify({"error": "La contraseña debe tener al menos 6 caracteres"}), 400
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))
        conn.commit()
        user_id = c.lastrowid
        conn.close()
        
        init_user_db(user_id)
        session['user_id'] = user_id
        session['username'] = username
        return jsonify({"success": True, "message": "Cuenta creada"})
    except sqlite3.IntegrityError:
        conn.close()
        return jsonify({"error": "El usuario ya existe"}), 400

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})

@app.route("/check_session")
def check_session():
    if 'user_id' in session:
        return jsonify({"authenticated": True, "username": session.get('username')})
    return jsonify({"authenticated": False})

# ─────────────────────────────────────────────────────
# RUTAS - PRINCIPALES
# ─────────────────────────────────────────────────────
@app.route("/")
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template("index.html")


@app.route("/api/calcular_indice", methods=["POST"])
@login_required
def api_calcular_indice():
    data = request.json
    filas = data.get("asignaturas", [])
    modo = data.get("modo", "reemplazar")
    if not filas:
        return jsonify({"error": "Sin asignaturas."}), 400
    try:
        historial = _reconstruir_historial(filas)
        resultado = calcular_indice_acumulado(historial, modo)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/calcular_notas", methods=["POST"])
@login_required
def api_calcular_notas():
    data = request.json
    try:
        notas = [float(data["p1"]), float(data["p2"]), float(data["prac"]), float(data["fin"])]
        semanas = int(data.get("semanas", 15))
        politica = data.get("politica", "Round")
        resultado = calcular_notas(notas, semanas, politica)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/calcular_costos", methods=["POST"])
@login_required
def api_calcular_costos():
    data = request.json
    try:
        cred = float(data["creditos"])
        tipo = data["tipo"]
        categoria = data["categoria"]
        horas = calcular_horas(cred, tipo)
        tarifa = TARIFAS[categoria]
        total = calcular_costo_total(tarifa, horas)
        return jsonify({"horas": horas, "tarifa": tarifa, "total": round(total, 2),
                        "formula": f"({tarifa} × {horas}) × 2"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/calcular_fpf", methods=["POST"])
@login_required
def api_calcular_fpf():
    data = request.json
    try:
        periodo = data["periodo"]
        año = int(data["año"])
        ncuat = int(data["ncuat"])
        año_actual = datetime.date.today().year
        calendario = generar_calendario_auto(año_actual - 2, año_actual + 12)
        plan = generar_plan_fpf(periodo, año, ncuat, calendario)
        fpf = plan[-1]["fecha_fin"] if plan and plan[-1]["fecha_fin"] else None
        return jsonify({"plan": plan, "fpf": fpf})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/calcular_horas_creditos", methods=["POST"])
@login_required
def api_calcular_horas_creditos():
    data = request.json
    try:
        ht = float(data.get("ht", 0))
        hp = float(data.get("hp", 0))
        hi = float(data.get("hi", 0))
        semanas = float(data.get("semanas", 15))
        politica = data.get("politica", "Round")
        if ht < 0 or hp < 0 or hi < 0:
            return jsonify({"error": "Las horas no pueden ser negativas."}), 400
        if ht + hp + hi == 0:
            return jsonify({"error": "Ingresa al menos un tipo de horas."}), 400
        resultado = calcular_horas_creditos(ht, hp, hi, semanas, politica)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/periodos")
def api_periodos():
    return jsonify({"periodos": PERIODOS})


@app.route("/api/tarifas")
def api_tarifas():
    return jsonify({"tarifas": list(TARIFAS.keys())})


if __name__ == "__main__":
    app.run(debug=True, port=5050)

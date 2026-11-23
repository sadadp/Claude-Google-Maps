"""Genera las demos, el panel de ventas y MENSAJES_PARA_ENVIAR.txt. Uso: python3 build.py"""
import json, re, subprocess
from pathlib import Path
from urllib.parse import quote
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).parent
url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
user, repo = re.findall(r"[^/:]+", url.removesuffix(".git"))[-2:]
BASE_URL = f"https://{user.lower()}.github.io/{repo}"

TEMAS = {
    "dentista": {
        "titulo": "Dentista", "quienes": "pacientes",
        "colores": {"50": "#f2f7fc", "100": "#e1ecf8", "200": "#bcd6f0", "300": "#88b6e3", "400": "#4d8fd1",
                    "700": "#1d5ea8", "800": "#194e8a", "900": "#163f6e", "950": "#0d2645"},
        "h1": "Tu cita dental en {zona}, a un mensaje de distancia",
        "sub": "{servicios} y más. Escríbenos por WhatsApp y te damos horario el mismo día.",
        "h2_servicios": "Lo que podemos hacer por tu sonrisa",
        "cita": "Hola, me gustaría agendar una cita dental.",
        "pasos": [("Escríbenos por WhatsApp", "Cuéntanos qué necesitas o si es urgencia."),
                  ("Elige tu horario", "Te proponemos el espacio más cercano disponible."),
                  ("Llega a tu cita", "Te esperamos con tu valoración lista.")],
        "cierre": "¿Te duele algo o ya toca tu limpieza? Agenda hoy.",
    },
    "veterinaria": {
        "titulo": "Veterinaria", "quienes": "dueños de mascotas",
        "colores": {"50": "#f0faf6", "100": "#d9f2e7", "200": "#b0e3cd", "300": "#79ccab", "400": "#3fae86",
                    "700": "#047857", "800": "#065f46", "900": "#064e3b", "950": "#022c22"},
        "h1": "Tu mascota, atendida en {zona} por gente que la cuida como suya",
        "sub": "{servicios} y más. Escríbenos por WhatsApp y te decimos cuándo pasar.",
        "h2_servicios": "Servicios para tu mascota",
        "cita": "Hola, quiero agendar una cita para mi mascota.",
        "pasos": [("Escríbenos por WhatsApp", "Dinos qué le pasa a tu mascota o qué servicio buscas."),
                  ("Te damos horario", "Te confirmamos el espacio disponible más cercano."),
                  ("Tráela a consulta", "La atendemos y te explicamos todo con calma.")],
        "cierre": "¿Le toca vacuna, baño o revisión? Agenda hoy.",
    },
}

env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
landing = env.get_template("landing.html")
prospectos = json.loads((ROOT / "prospectos.json").read_text(encoding="utf-8"))
mensajes = json.loads((ROOT / "mensajes.json").read_text(encoding="utf-8"))

filas, txt = [], []
for i, p in enumerate(prospectos, 1):
    zona = "San Andrés Cholula" if "San Andrés Cholula" in p["direccion"] else "Tlaxcalancingo"
    base = TEMAS[p["giro"]]
    t = {**base, "h1": base["h1"].format(zona=zona),
         "sub": base["sub"].format(servicios=f"{p['servicios'][0]}, {p['servicios'][1].lower()}")}
    wa_base = f"https://wa.me/{p['whatsapp_num']}?text="
    html = landing.render(
        p=p, t=t, zona=zona, wa_base=wa_base, wa_cita=wa_base + quote(t["cita"]),
        horario=p["horario"].split(", "),
        maps_url="https://www.google.com/maps/search/?api=1&query=" + quote(f"{p['nombre']}, {p['direccion']}"),
    )
    out = ROOT / "demos" / p["slug"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    demo = f"{BASE_URL}/demos/{p['slug']}/"
    msg = mensajes[p["slug"]].format(link=demo)
    wa = f"https://wa.me/{p['whatsapp_num']}?text={quote(msg)}"
    filas.append({**p, "n": i, "demo": demo, "msg": msg, "wa": wa})
    txt.append(f"{i}. {p['nombre']} | {p['telefono_display']}\n{msg}\n{wa}\n")

(ROOT / "index.html").write_text(env.get_template("panel.html").render(filas=filas, base=BASE_URL), encoding="utf-8")
(ROOT / "MENSAJES_PARA_ENVIAR.txt").write_text("\n".join(txt), encoding="utf-8")
print(f"OK: {len(filas)} demos | panel: {BASE_URL}/")

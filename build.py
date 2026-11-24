"""Genera las demos, el panel de ventas y MENSAJES_PARA_ENVIAR.txt. Uso: python3 build.py"""
import json, re, subprocess
from pathlib import Path
from urllib.parse import quote
from jinja2 import Environment, FileSystemLoader

ROOT = Path(__file__).parent
url = subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True, text=True, cwd=ROOT).stdout.strip()
user, repo = re.findall(r"[^/:]+", url.removesuffix(".git"))[-2:]
BASE_URL = f"https://{user.lower()}.github.io/{repo}"

FUENTES = {  # parámetros de Google Fonts por familia
    "Instrument Serif": "Instrument+Serif:ital@0;1",
    "Playfair Display": "Playfair+Display:ital,wght@0,400;0,500;0,700;1,400",
    "Cormorant Garamond": "Cormorant+Garamond:ital,wght@0,500;0,700;1,500",
    "Fraunces": "Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;1,9..144,400",
    "Space Grotesk": "Space+Grotesk:wght@400;500;700",
    "Syne": "Syne:wght@500;700;800",
    "Inter": "Inter:wght@400;500;600",
    "DM Sans": "DM+Sans:wght@400;500;700",
    "Plus Jakarta Sans": "Plus+Jakarta+Sans:wght@400;500;600",
}
# Textos por giro: cita prellenada, botón, títulos de sección e intro (solo con datos reales del negocio)
GIROS = {
    "dentista": dict(cita="Hola, me gustaría agendar una cita.", btn="Agendar por WhatsApp", sec="Servicios",
                     h2="Lo que atendemos", cta="Agenda tu cita →", intro="{a}, {b} y más. Escríbenos por WhatsApp y te damos tu cita."),
    "veterinaria": dict(cita="Hola, quiero agendar una cita para mi mascota.", btn="Agendar por WhatsApp", sec="Servicios",
                        h2="Lo que atendemos", cta="Agenda tu cita →", intro="{a}, {b} y más para tu mascota. Escríbenos por WhatsApp y te decimos cuándo pasar."),
    "barberia": dict(cita="Hola, quiero apartar un lugar para corte.", btn="Apartar lugar por WhatsApp", sec="Servicios",
                     h2="En la silla", cta="Aparta tu lugar →", intro="{a}, {b} y más. Escríbenos por WhatsApp y te apartamos lugar."),
    "restaurante": dict(cita="Hola, quisiera información.", btn="Escribir por WhatsApp", sec="De la carta",
                        h2="Para pedir", cta="Escríbenos →", intro="{a}, {b} y más. Escríbenos por WhatsApp para cualquier duda."),
    "gimnasio": dict(cita="Hola, quiero informes para ir a conocer el gym.", btn="Pedir informes por WhatsApp", sec="En el gym",
                     h2="Lo que hay", cta="Ven a conocernos →", intro="{a}, {b} y más. Escríbenos por WhatsApp y te damos informes."),
}
ETIQ_GIRO = {"dentista": "Consultorio dental", "barberia": "Barbería", "restaurante": "Café y cocina", "gimnasio": "Gimnasio"}


def giro_label(p):
    if p["giro"] in ETIQ_GIRO:
        return ETIQ_GIRO[p["giro"]]
    return next((g for g in ("Hospital Veterinario", "Centro Médico Veterinario") if g in p["nombre"]), "Clínica veterinaria").capitalize()


def intro(p):
    a, b = (item(x)[0] for x in p["servicios"][:2])
    return GIROS[p["giro"]]["intro"].format(a=a, b=b if p["giro"] == "restaurante" else b.lower())


def item(x):
    """'Café Lotus ($90)' -> ('Café Lotus', '$90'); sin precio -> (x, '')"""
    m = re.match(r"(.*?)\s*\((\$\d[\d,]*)\)$", x)
    return (m[1], m[2]) if m else (x, "")


env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True)
marcas = json.loads((ROOT / "marcas.json").read_text(encoding="utf-8"))
prospectos = json.loads((ROOT / "prospectos.json").read_text(encoding="utf-8"))
mensajes = json.loads((ROOT / "mensajes.json").read_text(encoding="utf-8"))

ETIQUETAS = [("m1", "Mensaje 1"), ("m2", "Mensaje 2"), ("m3", "Mensaje 3"), ("seg", "Seguimiento (48 h)")]
filas, txt = [], []
for i, p in enumerate(prospectos, 1):
    p = {**p, "servicios": p.get("servicios") or p["items"]}
    g = GIROS[p["giro"]]
    m = marcas[p["slug"]]
    nom = p["nombre"].split(" | ")[0]
    corto = re.sub(r"^(Dra\. |Hospital Veterinario |Consultorio (Dental |Dentista )?)", "", nom)
    *ini, fin = nom.split(" ")
    html = env.get_template(f"layouts/{m['layout']}.html").render(
        p={**p, "nombre": nom}, m=m, fq={"display": FUENTES[m["display"]], "sans": FUENTES[m["sans"]]},
        wa=f"https://wa.me/{p['whatsapp_num']}?text={quote(g['cita'])}",
        tel=f"tel:+52{p['whatsapp_num'][3:]}",
        maps="https://www.google.com/maps/search/?api=1&query=" + quote(f"{nom}, {p['direccion']}"),
        horas=[tuple(h.split(" ", 1)) for h in p["horario"].split(", ")],
        giro_label=giro_label(p), intro=intro(p), g=g, items=[item(x) for x in p["servicios"]], mono=corto[0],
        titulo=" ".join(ini) + f" <em>{fin}</em>",
    )
    out = ROOT / "demos" / p["slug"] / "index.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")

    demo = f"{BASE_URL}/demos/{p['slug']}/"
    wa = f"https://wa.me/{p['whatsapp_num']}"
    msgs = [(et, mensajes[p["slug"]][k].format(link=demo)) for k, et in ETIQUETAS]
    msgs = [(et, m, f"{wa}?text={quote(m)}") for et, m in msgs]
    filas.append({**p, "n": i, "demo": demo, "wa": wa, "msgs": msgs})
    txt.append(f"{i}. {p['nombre']} | {p['telefono_display']} | {wa}\n" + "".join(f"{et}: {m}\n" for et, m, _ in msgs))

(ROOT / "index.html").write_text(env.get_template("panel.html").render(filas=filas, base=BASE_URL), encoding="utf-8")
(ROOT / "MENSAJES_PARA_ENVIAR.txt").write_text("\n".join(txt), encoding="utf-8")
print(f"OK: {len(filas)} demos | panel: {BASE_URL}/")

# Sistema de ventas: landings para dentistas y veterinarias

Oferta: landing profesional con botón de citas a WhatsApp, $3,000 MXN pago único, entrega en 48 h.
Mercado: dentistas y veterinarias sin sitio propio en Tlaxcalancingo y San Andrés Cholula, Puebla.

## Archivos
- `prospectos.json`: los 12 negocios (datos públicos de Google Maps). Fuente de verdad.
- `mensajes.json`: mensaje de WhatsApp por slug; `{link}` se reemplaza con la URL de la demo.
- `templates/landing.html`: plantilla Jinja2 + Tailwind CDN. Paleta por giro en `TEMAS` de `build.py` (azul clínico dentista, esmeralda veterinaria).
- `templates/panel.html`: Panel de Ventas (Abrir WhatsApp, Copiar mensaje, Ver demo).
- `templates/wa.svg`: ícono de WhatsApp.
- `build.py`: lee `git remote get-url origin` → `BASE_URL=https://<usuario>.github.io/<repo>`; genera `demos/<slug>/index.html`, `index.html` y `MENSAJES_PARA_ENVIAR.txt`.

## Uso
    python3 build.py

Requisitos: Python 3.9+ y jinja2. Sin APIs de pago; el mapa es el embed público de Google Maps.

## Publicar
La rama `gh-pages` sirve el sitio: copiar `index.html`, `demos/` y `.nojekyll` a esa rama y hacer push.
El panel lleva `noindex`, pero GitHub Pages es público: cualquiera con el link puede verlo.

## Agregar un prospecto
1. Añadir el objeto a `prospectos.json` (mismo formato, `whatsapp_num` con 521 + 10 dígitos).
2. Añadir su mensaje a `mensajes.json` (3-4 líneas, usted, calificación real y zona, sin guiones largos).
3. `python3 build.py` y publicar.

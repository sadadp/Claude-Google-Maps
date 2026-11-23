# Sistema de ventas: landings para dentistas y veterinarias

Oferta: página profesional con botón de citas a WhatsApp + código QR, $700 MXN pago único, entrega en 48 h.
Mercado: dentistas y veterinarias sin sitio propio en Tlaxcalancingo y San Andrés Cholula, Puebla.

## Archivos
- `prospectos.json`: los 12 negocios (datos públicos de Google Maps). Fuente de verdad.
- `mensajes.json`: por slug, secuencia `m1` (rompehielos con dato real), `m2` (demo gratis, `{link}`), `m3` (oferta $700 + QR) y `seg` (seguimiento a las 48 h). Se mandan seguidos al mismo chat, cortos y en tono casual de Cholula.
- `templates/landing.html`: plantilla Jinja2 + Tailwind CDN. Paleta por giro en `TEMAS` de `build.py` (azul clínico dentista, esmeralda veterinaria).
- `templates/panel.html`: Panel de Ventas. Enviar/Copiar por mensaje y generador de QR de la demo en el navegador (qrcodejs por cdnjs) con descarga PNG.
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
2. Añadir sus 4 mensajes a `mensajes.json` (cortos, dato real de su perfil, sin guiones largos ni tono de vendedor).
3. `python3 build.py` y publicar.

## Skills usadas
frontend-design (Ilm-Alan), humanizer (blader), copywriting / cold-email / marketing-psychology (coreyhaines31/marketingskills), marketing-psychology (borghei/Claude-Skills). Escaneadas con SkillSpector antes de instalar.

# Build-First Outreach

Pipeline autónomo en Python: encuentra negocios locales **sin sitio web** en Google Maps, les genera una landing page con Claude, la publica en Vercel y les envía la vista previa por WhatsApp (Evolution API).

```
scraper ─► SQLite (dedupe) ─► Claude (index.html) ─► Vercel (URL pública) ─► Evolution API (WhatsApp)
```

## Estructura

```
├── main.py                  # CLI orquestador (--niche, --location, --limit…)
├── config.py                # Settings tipados (pydantic-settings, .env)
├── src/
│   ├── scraper.py           # Places API (New) + importador gosom/omkarcloud; filtro estricto
│   ├── database.py          # SQLite leads.db, estados y control de duplicados
│   ├── builder.py           # Generación de index.html con el SDK de Anthropic
│   ├── deployer.py          # Deploy vía POST https://api.vercel.com/v13/deployments
│   ├── outreach.py          # Evolution API /message/sendText/{instance} + jitter
│   ├── http_utils.py        # Reintentos exponenciales (tenacity) para APIs externas
│   └── models.py            # Modelos Pydantic (Business, Lead, LeadStatus…)
├── templates/
│   ├── landing_system_prompt.md   # Prompt de sistema del diseñador web
│   └── outreach_message.txt       # Plantilla del mensaje de WhatsApp
├── tests/                   # pytest con transportes HTTP simulados (sin red)
├── docker-compose.yml       # Evolution API v2 + PostgreSQL + Redis
├── setup.sh                 # Instala dependencias y verifica variables
├── requirements.txt
└── .env.example
```

## Puesta en marcha

```bash
./setup.sh
```

La primera ejecución crea `.env` desde `.env.example`. Complétalo (`ANTHROPIC_API_KEY`, `VERCEL_TOKEN`, `EVOLUTION_API_KEY` y `GOOGLE_MAPS_API_KEY`) y vuelve a ejecutarlo.

### Evolution API (WhatsApp)

```bash
docker compose --env-file .env up -d
```

Crea la instancia y vincula el teléfono escaneando el QR:

```bash
curl -X POST http://localhost:8080/instance/create -H "apikey: $EVOLUTION_API_KEY" -H "Content-Type: application/json" -d '{"instanceName":"outreach","integration":"WHATSAPP-BAILEYS","qrcode":true}'
```

```bash
curl http://localhost:8080/instance/connect/outreach -H "apikey: $EVOLUTION_API_KEY"
```

(El panel web en `http://localhost:8080/manager` también muestra el QR.)

## Uso

```bash
source .venv/bin/activate
```

Primero en modo de prueba (genera y despliega, **no** envía WhatsApp):

```bash
python main.py --niche "barberías" --location "Puebla" --limit 15 --dry-run
```

Lote real:

```bash
python main.py --niche "barberías" --location "Puebla" --limit 15
```

Con la salida de [gosom/google-maps-scraper](https://github.com/gosom/google-maps-scraper) (`-json`) u [omkarcloud/google-maps-scraper](https://github.com/omkarcloud/google-maps-scraper) en lugar de la Places API:

```bash
python main.py --source gosom --input results.json --limit 15
```

Reanudar leads pendientes sin volver a buscar:

```bash
python main.py --skip-scrape --limit 15
```

## Comportamiento

| Etapa | Detalle |
|---|---|
| Filtro | Descarta negocios con `websiteUri`; exige teléfono internacional y `>= MIN_REVIEWS` (5) reseñas. Conserva las 3 reseñas de 5★ más completas. |
| Duplicados | `place_id` es PRIMARY KEY (`INSERT OR IGNORE`). Además, nunca se escribe dos veces al mismo número aunque aparezca en otra ficha. |
| Estados | `PENDING` → `GENERATED` (preview desplegada) → `SENT`. `REJECTED` = sin WhatsApp, teléfono duplicado o `MAX_ATTEMPTS` fallos. |
| Claude | `claude-sonnet-5-5` (configurable con `ANTHROPIC_MODEL`). Claude 3.5 Sonnet fue retirado en octubre de 2025; Sonnet 5.5 es el Sonnet actual. Streaming, reintentos del SDK y `fallbacks: "default"` por si el modelo declina. El HTML se valida (Tailwind CDN, `tel:`, `wa.me`, mapa) y se guarda en `output/<slug>/index.html`. |
| Vercel | Deploy de producción de un sitio estático; espera `readyState=READY` y devuelve el alias más corto (`https://<slug>.vercel.app`). |
| WhatsApp | Verifica que el número tenga WhatsApp, espera de 60 a 180 s aleatorios entre envíos, respeta `DAILY_SEND_CAP` y añade una línea para darse de baja. |
| Reintentos | 408/409/425/429/5xx y errores de red, con backoff exponencial y jitter (tenacity). |

## Uso responsable

Mensajear en frío a negocios está regulado (p.ej. la LFPDPPP en México, la TCPA y las leyes estatales en EE. UU., el RGPD en la UE) y los [términos de WhatsApp Business](https://www.whatsapp.com/legal/business-policy) limitan los mensajes no solicitados. Mantén lotes pequeños, honra cualquier respuesta tipo "no" (márcalo `REJECTED` en la BD) y no elimines la línea de baja. Las previews indican que no son el sitio oficial del negocio.

## Orquestación alternativa

Cada módulo es independiente, así que puedes llamar `main.py` desde un nodo *Execute Command* de [n8n](https://github.com/n8n-io/n8n) o programarlo con cron.

## Tests

```bash
python -m pytest -q
```

#!/usr/bin/env python3
"""Orquestador principal del pipeline Build-First Outreach.

Ejemplos:
    python main.py --niche "barberías" --location "Puebla" --limit 15
    python main.py --niche "plumbers" --location "Miami" --limit 10 --dry-run
    python main.py --source gosom --input results.json --limit 15
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from config import Settings, get_settings
from src.builder import BuildError, SiteBuilder, save_html
from src.database import LeadRepository
from src.deployer import VercelDeployer, slugify
from src.http_utils import ExternalAPIError
from src.models import Business, Lead, LeadStatus, PipelineResult
from src.outreach import EvolutionClient, Throttle, render_message
from src.scraper import scrape

console = Console()
log = logging.getLogger("pipeline")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Prospección local + sitio de vista previa + WhatsApp")
    p.add_argument("--niche", help='Nicho, p.ej. "barberías" o "plumbers"')
    p.add_argument("--location", help='Ciudad/zona, p.ej. "Puebla" o "Miami"')
    p.add_argument("--limit", type=int, default=15, help="Máximo de leads a procesar en este lote")
    p.add_argument("--source", choices=["places", "gosom", "omkarcloud", "file"], default="places",
                   help="Fuente de ingesta (Places API o export de un scraper)")
    p.add_argument("--input", type=Path, help="Export JSON/CSV para --source gosom/omkarcloud/file")
    p.add_argument("--dry-run", action="store_true",
                   help="Genera y despliega los sitios pero NO envía WhatsApp")
    p.add_argument("--skip-scrape", action="store_true",
                   help="No busca nuevos negocios; sólo procesa los pendientes en la BD")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if args.source == "places" and not args.skip_scrape and not (args.niche and args.location):
        p.error("--niche y --location son obligatorios con --source places")
    if args.source != "places" and not args.skip_scrape and not args.input:
        p.error("--input es obligatorio con --source gosom/omkarcloud/file")
    if args.limit < 1:
        p.error("--limit debe ser >= 1")
    return args


def ingest(settings: Settings, repo: LeadRepository, args: argparse.Namespace) -> tuple[int, int]:
    new = dup = 0
    with console.status("Buscando negocios sin sitio web…"):
        for biz in scrape(settings, args.niche or "", args.location or "",
                          source=args.source, input_path=args.input):
            if repo.insert_if_new(biz):
                new += 1
            else:
                dup += 1
            if new >= args.limit * 2:  # margen para descartes posteriores
                break
    return new, dup


def build_and_deploy(
    settings: Settings, repo: LeadRepository, builder: SiteBuilder, deployer: VercelDeployer,
    lead: Lead, biz: Business,
) -> str:
    slug = slugify(biz.name, biz.place_id, settings.vercel_project_prefix)
    console.print(f"  [cyan]Generando sitio con Claude[/] ({slug})…")
    html = builder.generate(biz)
    path = save_html(html, settings.output_dir, slug)
    console.print(f"  [cyan]Desplegando en Vercel[/] ({path.stat().st_size // 1024} KB)…")
    url = deployer.deploy(html, slug)
    repo.mark_generated(lead.place_id, url)
    return url


def run(args: argparse.Namespace) -> list[PipelineResult]:
    settings = get_settings()
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    repo = LeadRepository(settings.database_path)

    if not args.skip_scrape:
        new, dup = ingest(settings, repo, args)
        console.print(f"[bold]Ingesta:[/] {new} negocios nuevos, {dup} ya existentes (omitidos).")

    leads = repo.actionable(args.limit)
    if not leads:
        console.print("[yellow]No hay leads pendientes que procesar.[/]")
        return []

    builder = SiteBuilder(settings)
    deployer = VercelDeployer(settings)
    whatsapp: EvolutionClient | None = None
    send_enabled = not args.dry_run
    if send_enabled:
        whatsapp = EvolutionClient(settings)
        try:
            state = whatsapp.connection_state()
        except ExternalAPIError as exc:
            state = f"error: {exc}"
        if state != "open":
            console.print(f"[red]Instancia de WhatsApp no conectada ({state}); se omiten los envíos.[/]")
            send_enabled = False
    throttle = Throttle(settings.jitter_min_s, settings.jitter_max_s)

    results: list[PipelineResult] = []
    for i, lead in enumerate(leads, 1):
        console.rule(f"[{i}/{len(leads)}] {lead.name}")
        biz = repo.get_business(lead.place_id)
        note = ""
        try:
            if biz is None:
                raise BuildError("Lead sin datos de negocio en la BD")

            if lead.status == LeadStatus.PENDING or not lead.preview_url:
                lead.preview_url = build_and_deploy(settings, repo, builder, deployer, lead, biz)
                lead.status = LeadStatus.GENERATED
                console.print(f"  [green]Preview:[/] {lead.preview_url}")

            if send_enabled and whatsapp and lead.status == LeadStatus.GENERATED:
                if repo.sent_today() >= settings.daily_send_cap:
                    note = "tope diario de envíos alcanzado"
                elif repo.phone_already_contacted(biz.phone_digits, biz.place_id):
                    repo.mark_rejected(lead.place_id, "teléfono ya contactado")
                    lead.status, note = LeadStatus.REJECTED, "teléfono ya contactado"
                elif settings.verify_whatsapp_numbers and not whatsapp.has_whatsapp(biz.phone_digits):
                    repo.mark_rejected(lead.place_id, "número sin WhatsApp")
                    lead.status, note = LeadStatus.REJECTED, "número sin WhatsApp"
                else:
                    throttle.wait()
                    text = render_message(
                        biz.name, lead.preview_url or "",
                        footer=settings.opt_out_footer, sender=settings.sender_name,
                    )
                    whatsapp.send_text(biz.phone_digits, text)
                    repo.mark_sent(lead.place_id)
                    lead.status = LeadStatus.SENT
                    console.print("  [green]WhatsApp enviado.[/]")
            elif lead.status == LeadStatus.GENERATED:
                note = "dry-run" if args.dry_run else "envío omitido"
        except (BuildError, ExternalAPIError) as exc:
            lead.status = repo.record_failure(lead.place_id, str(exc), settings.max_attempts)
            note = str(exc)[:80]
            console.print(f"  [red]Error:[/] {exc}")
        except Exception as exc:  # noqa: BLE001 — un lead no debe tumbar el lote
            log.exception("Error inesperado procesando %s", lead.place_id)
            lead.status = repo.record_failure(lead.place_id, repr(exc), settings.max_attempts)
            note = f"inesperado: {type(exc).__name__}"

        results.append(PipelineResult(
            name=lead.name, phone=lead.phone, rating=lead.rating, review_count=lead.review_count,
            status=lead.status, preview_url=lead.preview_url, note=note,
        ))
    return results


STATUS_STYLE = {
    LeadStatus.SENT: "green", LeadStatus.GENERATED: "cyan",
    LeadStatus.PENDING: "yellow", LeadStatus.REJECTED: "red",
}


def print_summary(results: list[PipelineResult]) -> None:
    table = Table(title="Resumen del lote", show_lines=False)
    for col in ("#", "Negocio", "Teléfono", "★", "Reseñas", "Estado", "Preview", "Nota"):
        table.add_column(col, overflow="fold")
    for i, r in enumerate(results, 1):
        style = STATUS_STYLE[r.status]
        table.add_row(str(i), r.name, r.phone, f"{r.rating:.1f}", str(r.review_count),
                      f"[{style}]{r.status}[/]", r.preview_url or "—", r.note)
    console.print(table)
    counts = {s: sum(1 for r in results if r.status == s) for s in LeadStatus}
    console.print(" · ".join(f"[{STATUS_STYLE[s]}]{s}: {n}[/]" for s, n in counts.items()))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s", handlers=[RichHandler(console=console, show_path=False)],
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        results = run(args)
    except ValidationError as exc:
        console.print(f"[red]Configuración inválida. Revisa tu .env:[/]\n{exc}")
        return 2
    except (ExternalAPIError, ValueError) as exc:
        console.print(f"[red]Error:[/] {exc}")
        return 1
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrumpido. El progreso está guardado en la BD.[/]")
        return 130
    if results:
        print_summary(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())

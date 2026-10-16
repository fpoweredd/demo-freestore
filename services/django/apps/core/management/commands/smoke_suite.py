from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.test import Client


class Command(BaseCommand):
    help = "Run lightweight post-deploy smoke checks."

    def handle(self, *args, **options):
        client = Client()
        checks: list[tuple[str, str]] = [
            ("GET /healthz", "/healthz"),
            ("GET /readyz", "/readyz"),
            ("GET /", "/"),
        ]
        failed: list[str] = []
        for title, path in checks:
            resp = client.get(path)
            ok = 200 <= resp.status_code < 400
            self.stdout.write(
                f"{title}: {'OK' if ok else 'FAIL'} ({resp.status_code})"
            )
            if not ok:
                failed.append(f"{title} -> {resp.status_code}")
        if failed:
            raise CommandError("Smoke suite failed: " + "; ".join(failed))
        self.stdout.write(self.style.SUCCESS("Smoke suite passed."))

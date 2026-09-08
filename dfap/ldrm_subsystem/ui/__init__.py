"""Administrator, investigator and provider consoles (DFAP Stage 3 §23-§25, §30-§31).

Static, dependency-free pages served from the application itself. They call the
same authenticated API as any other client and hold no privileged state: every
control they offer is enforced in the backend, and a console cannot reach an
action the caller's role does not permit.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

STATIC = Path(__file__).parent / 'static'

console_router = APIRouter()

#: Only these pages are served. The path is never taken from the request.
PAGES = {'admin': 'admin.html', 'investigator': 'investigator.html', 'provider': 'provider.html'}
ASSETS = {'console.css': 'text/css', 'console.js': 'application/javascript'}


@console_router.get('/ldrm-console', include_in_schema=False)
def console_index():
    return RedirectResponse('/ldrm-console/admin')


@console_router.get('/ldrm-console/static/{asset}', include_in_schema=False)
def console_asset(asset: str):
    media_type = ASSETS.get(asset)
    if media_type is None:
        raise HTTPException(404, 'Not found')
    return FileResponse(STATIC / asset, media_type=media_type)


@console_router.get('/ldrm-console/{page}', include_in_schema=False)
def console_page(page: str):
    filename = PAGES.get(page)
    if filename is None:
        raise HTTPException(404, 'Not found')
    return FileResponse(STATIC / filename, media_type='text/html')


@console_router.get('/provider-console', include_in_schema=False)
def provider_console():
    """Served on its own path so the provider view stays logically separate."""
    return FileResponse(STATIC / 'provider.html', media_type='text/html')

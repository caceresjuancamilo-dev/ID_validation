"""
RUNT License Validator - Python
================================
Valida si una persona tiene licencia de conduccion vigente en el RUNT Colombia.

REQUISITOS:
    pip install playwright groq
    playwright install chromium

USO:
    python runt_license_validator.py 1014306477

VARIABLES DE ENTORNO:
    GROQ_API_KEY=gsk_xxxxx   (https://console.groq.com)
"""

import sys
import json
import base64
import os
import asyncio
from datetime import datetime, timezone

try:
    from playwright.async_api import async_playwright
except ImportError:
    print(json.dumps({"success": False, "error": "Instala: pip install playwright && playwright install chromium"}))
    sys.exit(1)

try:
    from groq import Groq
except ImportError:
    print(json.dumps({"success": False, "error": "Instala: pip install groq"}))
    sys.exit(1)

URL = "https://portalpublico.runt.gov.co/#/consulta-ciudadano-documento/consulta/consulta-ciudadano-documento"
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
CAPTCHA_REINTENTOS = 3
TIMEOUT_MS = 30_000


def resolver_captcha(imagen_base64: str) -> str:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY no configurada. Obtener en https://console.groq.com")
    client = Groq(api_key=GROQ_API_KEY)
    resp = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        max_tokens=50,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{imagen_base64}"}},
                {"type": "text", "text": "This image contains a CAPTCHA. Extract ONLY the exact characters shown, preserving uppercase and lowercase. Reply with ONLY the characters, nothing else."},
            ],
        }],
    )
    texto = resp.choices[0].message.content.strip()
    return "".join(c for c in texto if c.isalnum())


async def extraer_datos(page) -> dict:
    await page.wait_for_timeout(2000)

    # Datos del conductor
    conductor = await page.evaluate("""() => {
        const result = {};
        const todos = Array.from(document.querySelectorAll('*'));
        for (let i = 0; i < todos.length; i++) {
            const txt = todos[i].childElementCount === 0 ? todos[i].innerText.trim().toUpperCase() : '';
            if (!txt) continue;
            const sig = todos[i + 1] ? todos[i + 1].innerText.trim() : '';
            if (txt.includes('NOMBRE COMPLETO'))           result.nombre = sig;
            else if (txt === 'DOCUMENTO:')                 result.documento = sig;
            else if (txt.includes('ESTADO DE LA PERSONA')) result.estado_persona = sig;
            else if (txt.includes('ESTADO DEL CONDUCTOR')) result.estado_conductor = sig;
            else if (txt.includes('INSCRIPCI') && txt.includes('MERO')) result.numero_inscripcion = sig;
            else if (txt.includes('FECHA') && txt.includes('INSCRIPCI')) result.fecha_inscripcion = sig;
        }
        return result;
    }""")

    # Expandir acordeon de licencias
    elementos = await page.query_selector_all("mat-expansion-panel-header, .mat-expansion-panel-header")
    for el in elementos:
        txt = (await el.inner_text()).strip()
        if "icencia" in txt:
            await el.click()
            await page.wait_for_timeout(1500)
            break

    # Extraer tabla de licencias
    licencias = await page.evaluate("""() => {
        const licencias = [];
        const tablas = Array.from(document.querySelectorAll('table'));
        for (const tabla of tablas) {
            const ths = Array.from(tabla.querySelectorAll('th')).map(th => th.innerText.trim().toLowerCase());
            if (!ths.some(t => t.includes('estado') || t.includes('expedici') || t.includes('expide'))) continue;
            const filas = Array.from(tabla.querySelectorAll('tbody tr'));
            for (const fila of filas) {
                const celdas = Array.from(fila.querySelectorAll('td')).map(td => td.innerText.trim());
                if (celdas.length >= 3) {
                    licencias.push({
                        nro_licencia:     celdas[0] || null,
                        entidad_expide:   celdas[1] || null,
                        fecha_expedicion: celdas[2] || null,
                        estado:           celdas[3] || null,
                        restricciones:    celdas[4] || null,
                        retencion:        celdas[5] || null,
                    });
                }
            }
            if (licencias.length > 0) break;
        }
        return licencias;
    }""")

    licencia_activa = next((l for l in licencias if (l.get("estado") or "").upper() == "ACTIVA"), None)
    return {
        "conductor": conductor,
        "licencia_vigente": licencia_activa is not None,
        "licencia_activa": licencia_activa,
    }


async def validar_licencia(cedula: str) -> dict:
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = await browser.new_page()
        await page.set_viewport_size({"width": 1280, "height": 900})

        try:
            await page.goto(URL, wait_until="networkidle", timeout=TIMEOUT_MS)
            await page.wait_for_timeout(2000)

            # Seleccionar Cedula Ciudadania
            mat_select = await page.query_selector("mat-select")
            if mat_select:
                await mat_select.click()
                await page.wait_for_timeout(700)
                for opcion in await page.query_selector_all("mat-option"):
                    if "dula" in (await opcion.inner_text()):
                        await opcion.click()
                        break
            else:
                await page.select_option("select", label="Cedula Ciudadania")
            await page.wait_for_timeout(400)

            # Identificar inputs por posicion
            inputs_info = await page.evaluate("""() => Array.from(document.querySelectorAll('input')).map((el, idx) => ({
                index: idx, visible: el.offsetParent !== null, top: Math.round(el.getBoundingClientRect().top)
            }))""")
            inputs_visibles = sorted([i for i in inputs_info if i["visible"]], key=lambda x: x["top"])

            if len(inputs_visibles) < 2:
                raise RuntimeError(f"Solo {len(inputs_visibles)} inputs visibles, se esperaban 2")

            todos = await page.query_selector_all("input")
            campo_doc     = todos[inputs_visibles[0]["index"]]
            campo_captcha = todos[inputs_visibles[1]["index"]]

            # Llenar cedula
            await campo_doc.click(click_count=3)
            await campo_doc.fill(cedula)
            await page.wait_for_timeout(400)

            # Resolver CAPTCHA
            resuelto = False
            for intento in range(1, CAPTCHA_REINTENTOS + 1):
                bb = await campo_captcha.bounding_box()
                if not bb:
                    raise RuntimeError("No se pudo obtener posicion del input captcha")

                clip = {"x": max(0, bb["x"] - 20), "y": max(0, bb["y"] - 160), "width": 400, "height": 140}
                img_bytes = await page.screenshot(clip=clip)

                with open(f"/tmp/runt_captcha_{intento}.png", "wb") as f:
                    f.write(img_bytes)

                texto_captcha = resolver_captcha(base64.b64encode(img_bytes).decode())
                print(f"[Intento {intento}] CAPTCHA: '{texto_captcha}'", file=sys.stderr)

                await campo_captcha.click(click_count=3)
                await campo_captcha.fill(texto_captcha)
                await page.wait_for_timeout(300)

                # Click en Consultar
                btn = await page.query_selector('button[type="submit"]')
                if not btn:
                    for b in await page.query_selector_all("button"):
                        if "Consultar" in (await b.inner_text()):
                            btn = b
                            break
                if not btn:
                    raise RuntimeError("No se encontro el boton Consultar")

                await btn.click()
                await page.wait_for_timeout(3500)

                error_el  = await page.query_selector("mat-error, .error-captcha")
                result_el = await page.query_selector("table, mat-expansion-panel")

                if result_el and not error_el:
                    resuelto = True
                    break

                print(f"[Intento {intento}] CAPTCHA incorrecto, reintentando...", file=sys.stderr)
                await page.wait_for_timeout(1000)

            if not resuelto:
                raise RuntimeError(f"No se pudo resolver el CAPTCHA despues de {CAPTCHA_REINTENTOS} intentos.")

            datos = await extraer_datos(page)
            return {"success": True, "cedula": cedula, **datos}

        except Exception as e:
            return {"success": False, "cedula": cedula, "error": str(e)}
        finally:
            await browser.close()


if __name__ == "__main__":
    cedula_arg = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not cedula_arg or not cedula_arg.isdigit():
        print(json.dumps({"success": False, "error": "Uso: python runt_license_validator.py <cedula>"}))
        sys.exit(1)

    resultado = asyncio.run(validar_licencia(cedula_arg))
    resultado["timestamp"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(resultado, ensure_ascii=False, indent=2))

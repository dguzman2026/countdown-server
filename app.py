"""
Countdown GIF Server — Megasport Newsletter Tool
Genera GIFs de cuenta atrás en tiempo real para insertar en emails.

Uso:
  GET /countdown.gif?end=2025-06-30T23:59:59&bg=000000&fg=FFD700&lbl=FFFFFF&w=480&h=140

Parámetros:
  end  — fecha/hora objetivo en ISO 8601 (requerido)
  bg   — color fondo hex sin # (defecto: 000000)
  fg   — color dígitos hex sin # (defecto: FFD700)
  lbl  — color etiquetas hex sin # (defecto: FFFFFF)
  w    — ancho en px (defecto: 480)
  h    — alto en px (defecto: 140)
  spd  — ms por frame (defecto: 1000)
  tz   — timezone offset en horas respecto UTC (defecto: 1 para España)
"""

import io
import os
import urllib.request
from datetime import datetime, timezone, timedelta

from flask import Flask, request, send_file, Response
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

# Fuente: Anton (Google Fonts, libre uso SIL OFL)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_FONT = os.path.join(BASE_DIR, "Anton-Regular.ttf")
ANTON_URL = "https://fonts.gstatic.com/s/anton/v25/1Ptgg87LROyAm0K08i4gS7lu.ttf"

# Estado global para diagnóstico
FONT_PATH_USED = None


def ensure_font():
    """Si la fuente no existe la descarga al directorio del servidor."""
    if os.path.exists(BUNDLED_FONT) and os.path.getsize(BUNDLED_FONT) > 10000:
        return BUNDLED_FONT
    try:
        # Si existe pero está corrupta/pequeña, la borramos
        if os.path.exists(BUNDLED_FONT):
            os.remove(BUNDLED_FONT)
        # Algunos servidores requieren writable temp dir si BASE_DIR es read-only
        target = BUNDLED_FONT
        try:
            urllib.request.urlretrieve(ANTON_URL, target)
        except (OSError, PermissionError):
            target = os.path.join("/tmp", "Anton-Regular.ttf")
            urllib.request.urlretrieve(ANTON_URL, target)
        if os.path.getsize(target) > 10000:
            return target
    except Exception as e:
        print(f"[font] No se pudo descargar Anton: {e}")
    return None


def load_font(size):
    """Carga la fuente Anton (descargándola si hace falta) con fallbacks del sistema."""
    global FONT_PATH_USED
    candidates = []

    # 1. Fuente Anton (descargada o empaquetada)
    anton_path = ensure_font()
    if anton_path:
        candidates.append(anton_path)

    # 2. Fallbacks del sistema
    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        r"C:\Windows\Fonts\impact.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
    ])

    for path in candidates:
        try:
            font = ImageFont.truetype(path, size)
            FONT_PATH_USED = path
            return font
        except (IOError, OSError):
            continue

    FONT_PATH_USED = "DEFAULT_BITMAP_FONT (problema!)"
    return ImageFont.load_default()


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def darken(hex_color, amount=20):
    """Si amount es positivo oscurece, si es negativo aclara."""
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i+2], 16) for i in (0, 2, 4))
        if amount < 0:
            r, g, b = min(255, r - amount), min(255, g - amount), min(255, b - amount)
        else:
            r, g, b = max(0, r - amount), max(0, g - amount), max(0, b - amount)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return hex_color


LABELS = {
    "es": ("DÍAS",  "HORAS",   "MINUTOS", "SEGUNDOS"),
    "fr": ("JOURS", "HEURES",  "MINUTES", "SECONDES"),
    "pt": ("DIAS",  "HORAS",   "MINUTOS", "SEGUNDOS"),
}


def draw_frame(width, height, days, hours, minutes, seconds, bg, fg, lbl, lang="es"):
    img = Image.new("RGB", (width, height), f"#{bg}")
    draw = ImageDraw.Draw(img)

    # Dígitos GRANDES y bien proporcionados (estilo Megasport)
    digit_size = max(int(height * 0.55), 28)
    label_size = max(int(height * 0.16), 12)

    digit_font = load_font(digit_size)
    label_font = load_font(label_size)

    values = [days, hours, minutes, seconds]
    labels = LABELS.get(lang, LABELS["es"])
    block_w = width // 4

    # Línea vertical de los separadores
    sep_color = darken(f"#{bg}", -40) if bg.lower() in ("000000", "111111") else "#444444"

    for i, (val, label_text) in enumerate(zip(values, labels)):
        x_center = i * block_w + block_w // 2

        # Número (centrado vertical en la mitad superior)
        num_str = f"{val:02d}"
        bbox = draw.textbbox((0, 0), num_str, font=digit_font)
        nw = bbox[2] - bbox[0]
        nh = bbox[3] - bbox[1]
        nx = x_center - nw // 2
        ny = int(height * 0.18) - bbox[1]
        draw.text((nx, ny), num_str, fill=f"#{fg}", font=digit_font)

        # Etiqueta (debajo, centrada)
        bbox_l = draw.textbbox((0, 0), label_text, font=label_font)
        lw = bbox_l[2] - bbox_l[0]
        lx = x_center - lw // 2
        ly = int(height * 0.74)
        draw.text((lx, ly), label_text, fill=f"#{lbl}", font=label_font)

        # Separador vertical fino entre bloques
        if i < 3:
            sx = (i + 1) * block_w
            draw.line(
                [(sx, int(height * 0.20)), (sx, int(height * 0.80))],
                fill=sep_color, width=1
            )

    return img


def generate_gif(target_dt, bg, fg, lbl, width, height, speed_ms, lang="es", n_frames=60):
    """Genera GIF con cuenta atrás real: cada frame decrementa 1 segundo
    propagando el cambio a minutos, horas y días."""
    now = datetime.now(tz=target_dt.tzinfo)
    diff = target_dt - now

    if diff.total_seconds() <= 0:
        frames_data = [(0, 0, 0, 0)] * n_frames
    else:
        total_seconds = int(diff.total_seconds())
        days = diff.days
        rem  = diff.seconds
        h    = rem // 3600
        m    = (rem % 3600) // 60
        s    = rem % 60
        d    = days

        frames_data = []
        for _ in range(n_frames):
            frames_data.append((d, h, m, s))
            # Decrementa 1 segundo y propaga
            s -= 1
            if s < 0:
                s = 59
                m -= 1
                if m < 0:
                    m = 59
                    h -= 1
                    if h < 0:
                        h = 23
                        d -= 1
                        if d < 0:
                            # Llegamos al fin: rellena el resto con 00:00:00:00
                            frames_data.extend(
                                [(0, 0, 0, 0)] * (n_frames - len(frames_data))
                            )
                            break

    # Render — modo paleta para reducir tamaño
    frames = []
    for (d, h, m, s) in frames_data:
        rgb = draw_frame(width, height, d, h, m, s, bg, fg, lbl, lang)
        frames.append(rgb.convert("P", palette=Image.Palette.ADAPTIVE, colors=16))

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        optimize=True,
        duration=speed_ms,
        loop=0,
        disposal=2,
    )
    buf.seek(0)
    return buf


@app.route("/countdown.gif")
def countdown():
    end_str = request.args.get("end")
    if not end_str:
        return Response("Parámetro 'end' requerido. Ejemplo: ?end=2025-06-30T23:59:59", 400)

    try:
        # Intentar parsear con o sin offset de timezone
        for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                target_dt = datetime.strptime(end_str, fmt)
                break
            except ValueError:
                continue
        else:
            return Response("Formato de fecha inválido. Usa: 2025-06-30T23:59:59", 400)

        # Si no tiene timezone, asumir Europa/Madrid (UTC+1 invierno / UTC+2 verano)
        if target_dt.tzinfo is None:
            tz_offset = int(request.args.get("tz", 2))  # defecto UTC+2 (verano)
            target_dt = target_dt.replace(tzinfo=timezone(timedelta(hours=tz_offset)))

    except Exception as e:
        return Response(f"Error en fecha: {e}", 400)

    bg   = request.args.get("bg",  "000000").lstrip("#")
    fg   = request.args.get("fg",  "FFD700").lstrip("#")
    lbl  = request.args.get("lbl", "FFFFFF").lstrip("#")
    w    = min(max(int(request.args.get("w", 480)), 200), 800)
    h    = min(max(int(request.args.get("h", 140)), 80),  300)
    spd  = min(max(int(request.args.get("spd", 1000)), 200), 3000)
    lang = request.args.get("lang", "es").lower()
    if lang not in LABELS:
        lang = "es"

    try:
        gif_buf = generate_gif(target_dt, bg, fg, lbl, w, h, spd, lang)
    except Exception as e:
        return Response(f"Error generando GIF: {e}", 500)

    response = send_file(
        gif_buf,
        mimetype="image/gif",
        as_attachment=False,
        download_name="countdown.gif",
    )
    # Cache HTTP de 30s — equilibrio entre carga del servidor
    # y precisión del countdown cuando se reabre el email
    response.headers["Cache-Control"] = "public, max-age=30"
    return response


@app.route("/")
def index():
    return """
    <html><body style="font-family:sans-serif;max-width:700px;margin:40px auto">
    <h2>⏱ Countdown Email Server</h2>
    <p>Genera GIFs de cuenta atrás para newsletters.</p>
    <h3>Uso:</h3>
    <pre>/countdown.gif?end=2025-06-30T23:59:59&bg=000000&fg=FFD700&lbl=FFFFFF&w=480&h=140</pre>
    <h3>Parámetros:</h3>
    <ul>
      <li><b>end</b> — Fecha/hora fin (requerido): <code>2025-06-30T23:59:59</code></li>
      <li><b>bg</b>  — Color fondo hex (defecto: 000000)</li>
      <li><b>fg</b>  — Color dígitos hex (defecto: FFD700)</li>
      <li><b>lbl</b> — Color etiquetas hex (defecto: FFFFFF)</li>
      <li><b>w</b>   — Ancho px (defecto: 480)</li>
      <li><b>h</b>   — Alto px (defecto: 140)</li>
      <li><b>spd</b> — Ms por frame (defecto: 1000)</li>
      <li><b>tz</b>  — Offset UTC para hora sin zona (defecto: 2)</li>
    </ul>
    <h3>Ejemplo:</h3>
    <img src="/countdown.gif?end=2026-01-01T00:00:00&bg=000000&fg=FFD700&lbl=FFFFFF">
    </body></html>
    """


@app.route("/diag")
def diag():
    """Diagnóstico: muestra qué fuente está usando el servidor."""
    load_font(40)  # fuerza carga
    info = {
        "font_path_used": FONT_PATH_USED,
        "bundled_font_exists": os.path.exists(BUNDLED_FONT),
        "bundled_font_size_bytes": os.path.getsize(BUNDLED_FONT) if os.path.exists(BUNDLED_FONT) else 0,
        "base_dir": BASE_DIR,
        "files_in_base_dir": os.listdir(BASE_DIR),
    }
    return info


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

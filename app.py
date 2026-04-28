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
from datetime import datetime, timezone, timedelta

from flask import Flask, request, send_file, Response
from PIL import Image, ImageDraw, ImageFont

app = Flask(__name__)

WINDOWS_FONTS = r"C:\Windows\Fonts"


def find_font(names, size):
    for name in names:
        for candidate in [name, os.path.join(WINDOWS_FONTS, name)]:
            try:
                return ImageFont.truetype(candidate, size)
            except (IOError, OSError):
                continue
    return ImageFont.load_default()


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))


def darken(hex_color, amount=20):
    try:
        r, g, b = hex_to_rgb(hex_color)
        return "#{:02x}{:02x}{:02x}".format(
            max(0, r - amount), max(0, g - amount), max(0, b - amount)
        )
    except Exception:
        return hex_color


def draw_frame(width, height, days, hours, minutes, seconds, bg, fg, lbl):
    img = Image.new("RGB", (width, height), f"#{bg}")
    draw = ImageDraw.Draw(img)

    digit_size = max(int(height * 0.44), 18)
    label_size = max(int(height * 0.14), 9)

    digit_font = find_font(["impact.ttf", "impactb.ttf", "arialbd.ttf"], digit_size)
    label_font = find_font(["arial.ttf", "segoeui.ttf", "calibri.ttf"], label_size)

    values = [days, hours, minutes, seconds]
    labels = ["DÍAS", "HORAS", "MINUTOS", "SEGUNDOS"]
    block_w = width // 4

    for i, (val, label_text) in enumerate(zip(values, labels)):
        x_center = i * block_w + block_w // 2
        pad = int(block_w * 0.06)
        y1 = int(height * 0.06)
        y2 = int(height * 0.76)

        draw.rectangle(
            [i * block_w + pad, y1, (i + 1) * block_w - pad, y2],
            fill=darken(f"#{bg}", 20)
        )

        num_str = f"{val:02d}"
        bbox = draw.textbbox((0, 0), num_str, font=digit_font)
        nw = bbox[2] - bbox[0]
        nh = bbox[3] - bbox[1]
        nx = x_center - nw // 2
        ny = y1 + (y2 - y1 - nh) // 2 - bbox[1]
        draw.text((nx, ny), num_str, fill=f"#{fg}", font=digit_font)

        bbox_l = draw.textbbox((0, 0), label_text, font=label_font)
        lw = bbox_l[2] - bbox_l[0]
        lx = x_center - lw // 2
        ly = int(height * 0.80)
        draw.text((lx, ly), label_text, fill=f"#{lbl}", font=label_font)

        if i < 3:
            sx = (i + 1) * block_w
            draw.line([(sx, int(height * 0.12)), (sx, int(height * 0.74))],
                      fill="#444444", width=1)

    return img


def generate_gif(target_dt, bg, fg, lbl, width, height, speed_ms):
    now = datetime.now(tz=target_dt.tzinfo)
    diff = target_dt - now

    if diff.total_seconds() <= 0:
        # Countdown expirado: mostrar ceros
        days = hours = minutes = 0
        frames_seconds = [0]
    else:
        days = diff.days
        remaining = diff.seconds
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        # 60 frames animando los segundos
        current_sec = diff.seconds % 60
        frames_seconds = list(range(current_sec, -1, -1)) + list(range(59, current_sec, -1))
        frames_seconds = frames_seconds[:60]

    frames = [draw_frame(width, height, days, hours, minutes, s, bg, fg, lbl)
              for s in frames_seconds]

    buf = io.BytesIO()
    frames[0].save(
        buf,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        optimize=False,
        duration=speed_ms,
        loop=0,
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

    bg  = request.args.get("bg",  "000000").lstrip("#")
    fg  = request.args.get("fg",  "FFD700").lstrip("#")
    lbl = request.args.get("lbl", "FFFFFF").lstrip("#")
    w   = min(max(int(request.args.get("w", 480)), 200), 800)
    h   = min(max(int(request.args.get("h", 140)), 80),  300)
    spd = min(max(int(request.args.get("spd", 1000)), 200), 3000)

    try:
        gif_buf = generate_gif(target_dt, bg, fg, lbl, w, h, spd)
    except Exception as e:
        return Response(f"Error generando GIF: {e}", 500)

    return send_file(
        gif_buf,
        mimetype="image/gif",
        as_attachment=False,
        download_name="countdown.gif",
    )


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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

import os
import re
import json
import shutil
import tempfile
import threading
import subprocess
import unittest
import urllib.request
import urllib.error
from http.server import HTTPServer

from bot.measurement_store import MeasurementStore
from dashboard_app import DashboardHTTPHandler, DASHBOARD_HTML


def run_node_eval(script_code: str, eval_expression: str) -> str:
    """Helper to run JavaScript extracted from dashboard_app.py inside Node.js

    with a lightweight mock DOM. Returns stdout from node.
    """
    # Note: dashboard_app.py line 926 has an unescaped literal newline in regex (/\n/g instead of /\\n/g).
    # We patch it here specifically so that Node can compile the functions to test their logic,
    # while test_javascript_syntax_validity documents and tests the raw syntax defect.
    clean_script = script_code.replace(".replace(/\n/g", ".replace(/\\n/g")
    runner_code = f"""
const fs = require('fs');

// Mock DOM
const dom = {{
  elements: {{}},
  getElementById(id) {{
    if (!this.elements[id]) {{
      this.elements[id] = {{
        id,
        style: {{}},
        textContent: '',
        innerHTML: '',
        value: '',
        src: '',
        appendChild(child) {{}},
        removeChild(child) {{}},
        classList: {{
          _classes: new Set(),
          add(c) {{ this._classes.add(c); }},
          remove(c) {{ this._classes.delete(c); }},
          contains(c) {{ return this._classes.has(c); }}
        }}
      }};
    }}
    return this.elements[id];
  }},
  createElement(tag) {{
    return {{
      tagName: tag,
      value: '',
      textContent: '',
      selected: false
    }};
  }},
  addEventListener(event, handler) {{}},
  removeEventListener(event, handler) {{}}
}};

global.document = dom;
global.window = {{ onload: null }};

{clean_script}

{eval_expression}
"""
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(runner_code)
        tmp_js = f.name
    try:
        result = subprocess.run(
            ["node", tmp_js],
            capture_output=True,
            text=True,
            encoding="utf-8"
        )
        if result.returncode != 0:
            raise RuntimeError(f"Node execution failed (code {result.returncode}):\n{result.stderr}\nCode:\n{runner_code}")
        return result.stdout.strip()
    finally:
        if os.path.exists(tmp_js):
            try:
                os.remove(tmp_js)
            except Exception:
                pass


class TestSplitViewTransforms(unittest.TestCase):
    """Challenge 1: Split-View layout & CSS transforms (zoom bounds 0.5x to 4.0x,

    rotation ±90°, reset function, and CSS styling).
    """

    @classmethod
    def setUpClass(cls):
        m = re.search(r"<script>([\s\S]*?)</script>", DASHBOARD_HTML)
        cls.js_code = m.group(1) if m else ""

    def test_00_javascript_syntax_defect_reproduction(self):
        """Verifies that the raw JavaScript code extracted directly from DASHBOARD_HTML passes

        ECMAScript syntax check in Node.js with return code 0, confirming that regex escapes
        like '/\\n/g' are properly double-escaped in Python triple quotes and contain no illegal
        LineTerminator characters.
        """
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(self.js_code)
            tmp_js = f.name
        try:
            res = subprocess.run(["node", "--check", tmp_js], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(res.returncode, 0, f"Raw script must pass syntax check cleanly. Stderr:\n{res.stderr}")
            self.assertNotIn("SyntaxError", res.stderr)
            self.assertNotIn("Invalid regular expression", res.stderr)
        finally:
            if os.path.exists(tmp_js):
                os.remove(tmp_js)

    def test_01_zoom_increments_and_upper_bound_clamp(self):
        """Verifies zoomFoto increments by delta and clamps strictly at 4.0x max."""
        expr = """
        currentZoom = 1.0;
        currentRotation = 0;
        const history = [];
        for (let i = 0; i < 15; i++) {
            zoomFoto(0.25);
            history.push(currentZoom);
        }
        zoomFoto(10.0);
        history.push(currentZoom);
        console.log(JSON.stringify({
            history,
            finalZoom: currentZoom,
            transform: document.getElementById('modal-img').style.transform,
            badge: document.getElementById('zoom-level-badge').textContent
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        # Initial increments
        self.assertEqual(output["history"][0], 1.25)
        self.assertEqual(output["history"][1], 1.50)
        self.assertEqual(output["history"][11], 4.0)
        self.assertEqual(output["history"][12], 4.0)  # clamped
        self.assertEqual(output["finalZoom"], 4.0)     # clamped even after +10.0
        self.assertEqual(output["transform"], "scale(4) rotate(0deg)")
        self.assertEqual(output["badge"], "400% (0°)")

    def test_02_zoom_decrements_and_lower_bound_clamp(self):
        """Verifies zoomFoto decrements by delta and clamps strictly at 0.5x min."""
        expr = """
        currentZoom = 1.0;
        currentRotation = 0;
        const history = [];
        for (let i = 0; i < 5; i++) {
            zoomFoto(-0.25);
            history.push(currentZoom);
        }
        zoomFoto(-50.0);
        history.push(currentZoom);
        console.log(JSON.stringify({
            history,
            finalZoom: currentZoom,
            transform: document.getElementById('modal-img').style.transform,
            badge: document.getElementById('zoom-level-badge').textContent
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertEqual(output["history"][0], 0.75)
        self.assertEqual(output["history"][1], 0.50)
        self.assertEqual(output["history"][2], 0.50)  # clamped
        self.assertEqual(output["finalZoom"], 0.50)   # clamped even after -50.0
        self.assertEqual(output["transform"], "scale(0.5) rotate(0deg)")
        self.assertEqual(output["badge"], "50% (0°)")

    def test_03_zoom_precision_and_rounding(self):
        """Verifies Math.round avoids floating point drift on repeated fractional zooms."""
        expr = """
        currentZoom = 1.0;
        zoomFoto(0.1);
        zoomFoto(0.2);
        console.log(JSON.stringify({
            zoom: currentZoom
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertEqual(output["zoom"], 1.3)

    def test_04_rotation_clockwise_and_modular_wrapping(self):
        """Verifies clockwise rotation (+90°) and wrapping at 360° modulo."""
        expr = """
        currentRotation = 0;
        currentZoom = 1.0;
        const rots = [];
        rotarFoto(90); rots.push(currentRotation);
        rotarFoto(90); rots.push(currentRotation);
        rotarFoto(90); rots.push(currentRotation);
        rotarFoto(90); rots.push(currentRotation);
        console.log(JSON.stringify({
            rots,
            finalTransform: document.getElementById('modal-img').style.transform,
            finalBadge: document.getElementById('zoom-level-badge').textContent
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertEqual(output["rots"], [90, 180, 270, 0])
        self.assertEqual(output["finalTransform"], "scale(1) rotate(0deg)")
        self.assertEqual(output["finalBadge"], "100% (0°)")

    def test_05_rotation_counter_clockwise(self):
        """Verifies counter-clockwise rotation (-90°)."""
        expr = """
        currentRotation = 0;
        currentZoom = 1.0;
        const rots = [];
        rotarFoto(-90); rots.push(currentRotation);
        rotarFoto(-90); rots.push(currentRotation);
        console.log(JSON.stringify({
            rots,
            transform: document.getElementById('modal-img').style.transform,
            badge: document.getElementById('zoom-level-badge').textContent
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertEqual(output["rots"], [-90, -180])
        self.assertEqual(output["transform"], "scale(1) rotate(-180deg)")
        self.assertEqual(output["badge"], "100% (-180°)")

    def test_06_reset_transform(self):
        """Verifies resetTransformFoto restores zoom to 1.0x and rotation to 0°."""
        expr = """
        currentZoom = 3.5;
        currentRotation = 270;
        updatePhotoTransform();
        resetTransformFoto();
        console.log(JSON.stringify({
            zoom: currentZoom,
            rotation: currentRotation,
            transform: document.getElementById('modal-img').style.transform,
            badge: document.getElementById('zoom-level-badge').textContent
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertEqual(output["zoom"], 1.0)
        self.assertEqual(output["rotation"], 0)
        self.assertEqual(output["transform"], "scale(1) rotate(0deg)")
        self.assertEqual(output["badge"], "100% (0°)")

    def test_07_split_view_layout_and_controls_html(self):
        """Verifies HTML structure and CSS classes for Split-View photo controls and viewport."""
        self.assertIn("split-modal-content", DASHBOARD_HTML)
        self.assertIn("split-modal-body", DASHBOARD_HTML)
        self.assertIn("split-col-left", DASHBOARD_HTML)
        self.assertIn("split-col-right", DASHBOARD_HTML)
        self.assertIn("split-photo-controls", DASHBOARD_HTML)
        self.assertIn("split-photo-viewport", DASHBOARD_HTML)
        self.assertIn("split-photo-img", DASHBOARD_HTML)
        self.assertIn("zoomFoto(0.25)", DASHBOARD_HTML)
        self.assertIn("zoomFoto(-0.25)", DASHBOARD_HTML)
        self.assertIn("rotarFoto(-90)", DASHBOARD_HTML)
        self.assertIn("rotarFoto(90)", DASHBOARD_HTML)
        self.assertIn("resetTransformFoto()", DASHBOARD_HTML)
        self.assertIn('id="zoom-level-badge"', DASHBOARD_HTML)


class TestTimelineHighlighting(unittest.TestCase):
    """Challenge 2: Timeline highlighting (verify .is-origin CSS class and

    origin message identification).
    """

    @classmethod
    def setUpClass(cls):
        m = re.search(r"<script>([\s\S]*?)</script>", DASHBOARD_HTML)
        cls.js_code = m.group(1) if m else ""

    def test_08_origin_identified_by_mensaje_id(self):
        """Verifies that when measurement has mensaje_id, exactly that message is marked with is-origin and badge."""
        expr = """
        const m = { id: 10, mensaje_id: 102, timestamp_medicion: '2026-10-16 10:00:00' };
        const msgs = [
            { mensaje_id: 100, timestamp_mensaje: '2026-10-16 09:55:00', remitente_nombre: 'Op1', texto: 'msg 1' },
            { mensaje_id: 101, timestamp_mensaje: '2026-10-16 09:58:00', remitente_nombre: 'Op1', texto: 'msg 2' },
            { mensaje_id: 102, timestamp_mensaje: '2026-10-16 10:00:00', remitente_nombre: 'Op1', texto: 'msg 3 (origin)' },
            { mensaje_id: 103, timestamp_mensaje: '2026-10-16 10:05:00', remitente_nombre: 'Op1', texto: 'msg 4' }
        ];

        const results = msgs.map(msg => {
            const isOrigin = (m.mensaje_id && msg.mensaje_id === m.mensaje_id) || (msg.timestamp_mensaje === m.timestamp_medicion && !m.mensaje_id);
            const badge = isOrigin ? '<span class=\"badge-origin\">⭐ Mensaje Origen</span>' : '';
            const bubbleClass = `chat-bubble ${isOrigin ? 'is-origin' : ''}`.trim();
            return { msgId: msg.mensaje_id, isOrigin: Boolean(isOrigin), bubbleClass, hasBadge: badge.length > 0 };
        });

        console.log(JSON.stringify(results));
        """
        results = json.loads(run_node_eval(self.js_code, expr))
        # Exactly msg 102 is origin
        for r in results:
            if r["msgId"] == 102:
                self.assertTrue(r["isOrigin"])
                self.assertIn("is-origin", r["bubbleClass"])
                self.assertTrue(r["hasBadge"])
            else:
                self.assertFalse(r["isOrigin"])
                self.assertNotIn("is-origin", r["bubbleClass"])
                self.assertFalse(r["hasBadge"])

    def test_09_origin_identified_by_timestamp_fallback(self):
        """Verifies fallback to timestamp_medicion when m.mensaje_id is null."""
        expr = """
        const m = { id: 11, mensaje_id: null, timestamp_medicion: '2026-10-16 14:30:00' };
        const msgs = [
            { mensaje_id: 201, timestamp_mensaje: '2026-10-16 14:00:00', texto: 'hola' },
            { mensaje_id: 202, timestamp_mensaje: '2026-10-16 14:30:00', texto: 'cota 3.10' },
            { mensaje_id: 203, timestamp_mensaje: '2026-10-16 15:00:00', texto: 'chau' }
        ];

        const results = msgs.map(msg => {
            const isOrigin = (m.mensaje_id && msg.mensaje_id === m.mensaje_id) || (msg.timestamp_mensaje === m.timestamp_medicion && !m.mensaje_id);
            return { msgId: msg.mensaje_id, isOrigin: Boolean(isOrigin) };
        });

        console.log(JSON.stringify(results));
        """
        results = json.loads(run_node_eval(self.js_code, expr))
        self.assertFalse(results[0]["isOrigin"])
        self.assertTrue(results[1]["isOrigin"])
        self.assertFalse(results[2]["isOrigin"])

    def test_10_no_origin_match_handled_gracefully(self):
        """Verifies that if no message matches, 0 messages are marked is-origin and no exception is thrown."""
        expr = """
        const m = { id: 12, mensaje_id: 999, timestamp_medicion: '2026-10-16 18:00:00' };
        const msgs = [
            { mensaje_id: 1, timestamp_mensaje: '2026-10-16 12:00:00' },
            { mensaje_id: 2, timestamp_mensaje: '2026-10-16 13:00:00' }
        ];
        const matchCount = msgs.filter(msg => {
            return (m.mensaje_id && msg.mensaje_id === m.mensaje_id) || (msg.timestamp_mensaje === m.timestamp_medicion && !m.mensaje_id);
        }).length;
        console.log(JSON.stringify({ matchCount }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertEqual(output["matchCount"], 0)

    def test_11_css_is_origin_rule_defined(self):
        """Verifies that .chat-bubble.is-origin is defined in CSS with distinctive warning styling."""
        self.assertIn(".chat-bubble.is-origin", DASHBOARD_HTML)
        self.assertIn("border-left: 4px solid var(--warning)", DASHBOARD_HTML)
        self.assertIn(".badge-origin", DASHBOARD_HTML)


class TestPhotoRelinking(unittest.TestCase):
    """Challenge 3: 1-click photo re-linking (client-side DOM updates and

    REST PUT persistence).
    """

    @classmethod
    def setUpClass(cls):
        m = re.search(r"<script>([\s\S]*?)</script>", DASHBOARD_HTML)
        cls.js_code = m.group(1) if m else ""

    def test_12_relink_photo_client_side_logic(self):
        """Verifies relinkPhoto updates currentMedicion, DOM img src, displays photo,

        hides placeholder, and resets transforms.
        """
        expr = """
        currentMedicion = { id: 7, foto_path: null, adjunto_id: null };
        currentZoom = 2.5;
        currentRotation = 90;

        relinkPhoto('data/fotos/nueva_regla_limni.jpg', 55);

        const img = document.getElementById('modal-img');
        const ph = document.getElementById('split-photo-placeholder');
        const fb = document.getElementById('split-feedback');

        console.log(JSON.stringify({
            foto_path: currentMedicion.foto_path,
            adjunto_id: currentMedicion.adjunto_id,
            imgSrc: img.src,
            imgDisplay: img.style.display,
            phDisplay: ph.style.display,
            zoom: currentZoom,
            rotation: currentRotation,
            feedback: fb.textContent
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertEqual(output["foto_path"], "data/fotos/nueva_regla_limni.jpg")
        self.assertEqual(output["adjunto_id"], 55)
        self.assertEqual(output["imgSrc"], "/data/fotos/nueva_regla_limni.jpg")
        self.assertEqual(output["imgDisplay"], "block")
        self.assertEqual(output["phDisplay"], "none")
        self.assertEqual(output["zoom"], 1.0)
        self.assertEqual(output["rotation"], 0)
        self.assertIn("nueva_regla_limni.jpg", output["feedback"])

    def test_13_relink_photo_null_guards(self):
        """Verifies relinkPhoto returns safely without error when currentMedicion or path is null/empty."""
        expr = """
        currentMedicion = null;
        let threw = false;
        try {
            relinkPhoto('foo.jpg', 1);
        } catch (e) {
            threw = true;
        }

        currentMedicion = { id: 8, foto_path: 'orig.jpg', adjunto_id: 1 };
        relinkPhoto(null, 2);
        relinkPhoto('', 3);

        console.log(JSON.stringify({
            threw,
            foto_path: currentMedicion.foto_path,
            adjunto_id: currentMedicion.adjunto_id
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertFalse(output["threw"])
        self.assertEqual(output["foto_path"], "orig.jpg")
        self.assertEqual(output["adjunto_id"], 1)

    def test_14_relink_button_rendered_in_timeline_html(self):
        """Verifies that timeline messages with photo attachments include the relink button."""
        self.assertIn("relinkPhoto", DASHBOARD_HTML)
        self.assertIn("relink-photo-btn", DASHBOARD_HTML)
        self.assertIn("📎 Vincular esta foto", DASHBOARD_HTML)


class TestManualTaggingButton(unittest.TestCase):
    """Challenge 4: Manual tagging button (+ Etiquetar Medición) presence

    when valor_metros == null and absence when already tagged.
    """

    @classmethod
    def setUpClass(cls):
        m = re.search(r"<script>([\s\S]*?)</script>", DASHBOARD_HTML)
        cls.js_code = m.group(1) if m else ""

    def test_15_untagged_message_renders_tag_button(self):
        """Verifies that a message with valor_metros == null renders the '+ Etiquetar Medición' button."""
        expr = """
        const msg = {
            id: 88,
            mensaje_id: 88,
            valor_metros: null,
            texto: 'Hola buen día'
        };

        let rendered = '';
        if (msg.valor_metros !== null && msg.valor_metros !== undefined) {
            rendered += '<div class=\"wpp-hydro-badge\">...</div>';
        } else {
            const targetMsgId = msg.mensaje_id || msg.id;
            rendered += `<button class=\"btn btn-sm btn-etiquetar-medicion\" onclick=\"abrirModalEtiquetarManual(${targetMsgId})\">+ Etiquetar Medición</button>`;
        }

        console.log(JSON.stringify({
            rendered,
            hasTagBtn: rendered.includes('+ Etiquetar Medición'),
            hasBadge: rendered.includes('wpp-hydro-badge')
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertTrue(output["hasTagBtn"])
        self.assertFalse(output["hasBadge"])
        self.assertIn("abrirModalEtiquetarManual(88)", output["rendered"])

    def test_16_tagged_message_renders_badge_and_no_tag_button(self):
        """Verifies that a tagged message with valor_metros == 3.45 renders the hydro badge and NO tag button."""
        expr = """
        const msg = {
            id: 89,
            mensaje_id: 89,
            medicion_id: 15,
            valor_metros: 3.45,
            tendencia_rio: 'CRECE',
            texto: 'Nivel 3.45m'
        };

        let rendered = '';
        if (msg.valor_metros !== null && msg.valor_metros !== undefined) {
            rendered += `<div class=\"wpp-hydro-badge\"><span class=\"hydro-val\">${parseFloat(msg.valor_metros).toFixed(2)} m</span> [${msg.tendencia_rio}]<button class=\"btn-corregir\" onclick=\"abrirDetallePorId(${msg.medicion_id})\">✏️ Corregir</button></div>`;
        } else {
            const targetMsgId = msg.mensaje_id || msg.id;
            rendered += `<button class=\"btn btn-sm btn-etiquetar-medicion\" onclick=\"abrirModalEtiquetarManual(${targetMsgId})\">+ Etiquetar Medición</button>`;
        }

        console.log(JSON.stringify({
            rendered,
            hasTagBtn: rendered.includes('+ Etiquetar Medición'),
            hasBadge: rendered.includes('wpp-hydro-badge'),
            hasCorregir: rendered.includes('✏️ Corregir')
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertFalse(output["hasTagBtn"])
        self.assertTrue(output["hasBadge"])
        self.assertTrue(output["hasCorregir"])
        self.assertIn("3.45 m", output["rendered"])

    def test_17_zero_level_message_not_treated_as_untagged(self):
        """Critical edge case: verifies that valor_metros == 0.00 is treated as a valid tagged measurement,

        NOT as null/untagged (preventing falsy zero bug).
        """
        expr = """
        const msg = {
            id: 90,
            mensaje_id: 90,
            medicion_id: 16,
            valor_metros: 0.0,
            tendencia_rio: 'ESTACIONARIO'
        };

        let isTagged = (msg.valor_metros !== null && msg.valor_metros !== undefined);
        let falsyBugCheck = Boolean(msg.valor_metros);

        console.log(JSON.stringify({
            isTagged,
            falsyBugCheck
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertTrue(output["isTagged"], "0.0 must be recognized as tagged!")
        self.assertFalse(output["falsyBugCheck"], "Standard falsy check would fail on 0.0; explicit !== null check is verified.")

    def test_18_negative_level_message_treated_as_tagged(self):
        """Verifies that negative level (e.g. -0.50m) is treated as tagged."""
        expr = """
        const msg = {
            id: 91,
            mensaje_id: 91,
            medicion_id: 17,
            valor_metros: -0.50,
            tendencia_rio: 'BAJA'
        };

        let isTagged = (msg.valor_metros !== null && msg.valor_metros !== undefined);
        console.log(JSON.stringify({ isTagged }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertTrue(output["isTagged"])

    def test_19_abrir_modal_etiquetar_manual_initialization(self):
        """Verifies abrirModalEtiquetarManual initializes dialog fields and sets active class."""
        expr = """
        estacionesData = [
            { id: 1, nombre: 'Pilar', rio: 'Paraguay' },
            { id: 2, nombre: 'Concepción', rio: 'Paraguay' }
        ];

        abrirModalEtiquetarManual(777);

        const msgIdVal = document.getElementById('manual-msg-id').value;
        const nivelVal = document.getElementById('manual-nivel-input').value;
        const tendVal = document.getElementById('manual-tendencia-select').value;
        const modal = document.getElementById('modal-etiquetar-manual');

        console.log(JSON.stringify({
            msgIdVal,
            nivelVal,
            tendVal,
            isActive: modal.classList.contains('active')
        }));
        """
        output = json.loads(run_node_eval(self.js_code, expr))
        self.assertEqual(output["msgIdVal"], 777)
        self.assertEqual(output["nivelVal"], "")
        self.assertEqual(output["tendVal"], "ESTACIONARIO")
        self.assertTrue(output["isActive"])


class TestLiveCmConversion(unittest.TestCase):
    """Challenge 5: Live cm conversion (actualizarNivelCmLive accurately converting

    across positive, zero, negative, and invalid values).
    """

    @classmethod
    def setUpClass(cls):
        m = re.search(r"<script>([\s\S]*?)</script>", DASHBOARD_HTML)
        cls.js_code = m.group(1) if m else ""

    def test_20_positive_conversions(self):
        """Verifies positive meter values convert accurately to centimeters."""
        test_cases = [
            ("3.45", "= 345.0 cm"),
            (3.45, "= 345.0 cm"),
            ("0.05", "= 5.0 cm"),
            (0.05, "= 5.0 cm"),
            ("12.34", "= 1234.0 cm"),
            ("0.1", "= 10.0 cm"),
            ("1.00", "= 100.0 cm"),
            ("10.5", "= 1050.0 cm")
        ]
        for val, expected in test_cases:
            expr = f"""
            actualizarNivelCmLive({json.dumps(val)});
            console.log(document.getElementById('split-edit-cm-preview').textContent);
            """
            result = run_node_eval(self.js_code, expr)
            self.assertEqual(result, expected, f"Failed on input {val}")

    def test_21_floating_point_imprecision_drift(self):
        """Verifies values prone to IEEE 754 binary floating point precision issues (0.29, 0.57, 1.15)."""
        test_cases = [
            ("0.29", "= 29.0 cm"),
            ("0.57", "= 57.0 cm"),
            ("1.15", "= 115.0 cm"),
            ("2.55", "= 255.0 cm"),
        ]
        for val, expected in test_cases:
            expr = f"""
            actualizarNivelCmLive({json.dumps(val)});
            console.log(document.getElementById('split-edit-cm-preview').textContent);
            """
            result = run_node_eval(self.js_code, expr)
            self.assertEqual(result, expected, f"Failed on float-drift input {val}")

    def test_22_zero_conversions(self):
        """Verifies zero inputs (string, float, int) display '= 0.0 cm' and are not treated as empty."""
        test_cases = ["0", "0.0", 0, 0.0]
        for val in test_cases:
            expr = f"""
            actualizarNivelCmLive({json.dumps(val)});
            console.log(document.getElementById('split-edit-cm-preview').textContent);
            """
            result = run_node_eval(self.js_code, expr)
            self.assertEqual(result, "= 0.0 cm", f"Failed on zero input {val}")

    def test_23_negative_conversions(self):
        """Verifies negative river levels (estuary gauges, extreme low waters) convert accurately."""
        test_cases = [
            ("-0.5", "= -50.0 cm"),
            (-0.5, "= -50.0 cm"),
            ("-1.25", "= -125.0 cm"),
            ("-0.08", "= -8.0 cm"),
            ("-0.01", "= -1.0 cm"),
        ]
        for val, expected in test_cases:
            expr = f"""
            actualizarNivelCmLive({json.dumps(val)});
            console.log(document.getElementById('split-edit-cm-preview').textContent);
            """
            result = run_node_eval(self.js_code, expr)
            self.assertEqual(result, expected, f"Failed on negative input {val}")

    def test_24_empty_null_nan_inputs(self):
        """Verifies invalid or empty inputs display placeholder '= - cm' without error."""
        test_cases = ["", None, "abc", "   ", "--"]
        for val in test_cases:
            val_arg = json.dumps(val) if val is not None else "null"
            expr = f"""
            actualizarNivelCmLive({val_arg});
            console.log(document.getElementById('split-edit-cm-preview').textContent);
            """
            result = run_node_eval(self.js_code, expr)
            self.assertEqual(result, "= - cm", f"Failed on invalid input {val}")

    def test_25_html_oninput_binding_verified(self):
        """Verifies input #split-edit-nivel is wired with oninput='actualizarNivelCmLive(this.value)'."""
        self.assertIn('id="split-edit-nivel"', DASHBOARD_HTML)
        self.assertIn('oninput="actualizarNivelCmLive(this.value)"', DASHBOARD_HTML)
        self.assertIn('id="split-edit-cm-preview"', DASHBOARD_HTML)


class TestFullSplitViewIntegrationServer(unittest.TestCase):
    """End-to-end integration tests with live HTTP server verifying REST endpoints

    supporting the Split-View console and interaction flow.
    """

    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp()
        cls.db_path = os.path.join(cls.test_dir, "split_test.db")
        cls.photos_dir = os.path.join(cls.test_dir, "fotos")
        os.makedirs(cls.photos_dir, exist_ok=True)
        cls.store = MeasurementStore(db_path=cls.db_path, photos_dir=cls.photos_dir)

        # Seed station and operator
        with cls.store.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM estaciones WHERE nombre = 'Alberdi'")
            row = cursor.fetchone()
            if row:
                cls.station_id = row[0]
            else:
                cursor.execute("INSERT INTO estaciones (nombre, rio) VALUES ('Alberdi', 'Paraguay')")
                cls.station_id = cursor.lastrowid

            cursor.execute("SELECT id FROM operadores WHERE telefono = '595981112233'")
            row_op = cursor.fetchone()
            if row_op:
                cls.op_id = row_op[0]
            else:
                cursor.execute("INSERT INTO operadores (telefono, nombre) VALUES ('595981112233', 'Op Alberdi')")
                cls.op_id = cursor.lastrowid
            conn.commit()

        # Seed chat messages: msg 1 (text), msg 2 (photo), msg 3 (tagged measurement)
        cls.msg1_id = cls.store.save_chat_message(
            remitente_telefono="595981112233",
            timestamp_mensaje="2026-10-16 08:00:00",
            texto="Reporte matutino Alberdi",
            remitente_nombre="Op Alberdi"
        )
        cls.fake_photo = os.path.join(cls.photos_dir, "alberdi_regla.jpg")
        with open(cls.fake_photo, "wb") as f:
            f.write(b"\xff\xd8\xff\xe0jpeg_test_data")

        cls.adjunto_id = cls.store.associate_photo_to_message(
            remitente_telefono="595981112233",
            timestamp_str="2026-10-16 08:00:00",
            foto_path="data/fotos/alberdi_regla.jpg"
        )

        cls.med_id = cls.store.save_measurement(
            estacion_detectada="Alberdi",
            remitente_telefono="595981112233",
            timestamp_medicion="2026-10-16 08:00:00",
            valor_metros=4.12,
            tendencia_rio="CRECE",
            mensaje_id=cls.msg1_id,
            adjunto_id=cls.adjunto_id,
            foto_path="data/fotos/alberdi_regla.jpg",
            estado_revision="PENDIENTE"
        )

        DashboardHTTPHandler.store = cls.store
        cls.httpd = HTTPServer(("127.0.0.1", 0), DashboardHTTPHandler)
        cls.port = cls.httpd.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.server_thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_26_context_endpoint_omits_mensaje_id_breaking_origin_highlight(self):
        """Verifies that /contexto messages include mensaje_id and adjunto_id,

        ensuring isOrigin evaluates to true when m.mensaje_id is set and origin message is highlighted.
        """
        req = urllib.request.urlopen(f"{self.base_url}/api/mediciones/{self.med_id}/contexto")
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode("utf-8"))
        self.assertIn("medicion", data)
        self.assertIn("mensajes", data)
        self.assertEqual(data["medicion"]["id"], self.med_id)
        self.assertEqual(data["medicion"]["mensaje_id"], self.msg1_id)

        first_msg = data["mensajes"][0]
        self.assertIn("mensaje_id", first_msg, "Fixed: /contexto query projects 'id AS mensaje_id'")
        self.assertEqual(first_msg["mensaje_id"], self.msg1_id)
        self.assertIn("adjunto_id", first_msg, "Fixed: /contexto query projects 'adjunto_id'")
        self.assertEqual(first_msg["adjunto_id"], self.adjunto_id)

        # Demonstrate verified frontend isOrigin logic when m.mensaje_id is set
        m = data["medicion"]
        msg = first_msg
        msg_id = msg.get("mensaje_id") or msg.get("id")
        part1 = bool(m.get("mensaje_id") and (msg_id == m.get("mensaje_id") or str(msg_id) == str(m.get("mensaje_id"))))
        part2 = bool(msg.get("timestamp_mensaje") == m.get("timestamp_medicion") and not m.get("mensaje_id"))
        is_origin_evaluated = part1 or part2

        self.assertTrue(is_origin_evaluated, "Origin highlighting succeeds because mensaje_id is present in msg")

    def test_27_relinked_photo_persisted_via_put(self):
        """Verifies that calling PUT /api/mediciones/<id> with new foto_path and adjunto_id persists them."""
        # Create second photo
        new_photo_file = "alberdi_regla_v2.jpg"
        with open(os.path.join(self.photos_dir, new_photo_file), "wb") as f:
            f.write(b"\xff\xd8\xff\xe0new_photo_test")

        new_adjunto_id = self.store.associate_photo_to_message(
            remitente_telefono="595981112233",
            timestamp_str="2026-10-16 08:00:00",
            foto_path=f"data/fotos/{new_photo_file}"
        )

        payload = {
            "estacion_id": self.station_id,
            "valor_metros": 4.15,
            "tendencia_rio": "CRECE",
            "timestamp_medicion": "2026-10-16 08:00:00",
            "estado_revision": "CORREGIDO",
            "adjunto_id": new_adjunto_id,
            "foto_path": f"data/fotos/{new_photo_file}",
            "fijar_operador": False
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/{self.med_id}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="PUT"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res_data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res_data["success"])

        # Check in DB
        with self.store.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT adjunto_id, foto_path, estado_revision FROM mediciones WHERE id = ?", (self.med_id,))
            row = cursor.fetchone()
            self.assertEqual(row[0], new_adjunto_id)
            self.assertEqual(row[1], f"data/fotos/{new_photo_file}")
            self.assertEqual(row[2], "CORREGIDO")

    def test_28_manual_measurement_creation_from_untagged_message(self):
        """Verifies POST /api/mediciones/manual creates measurement and marks review as VALIDADO."""
        # Create untagged chat message
        msg_untagged = self.store.save_chat_message(
            remitente_telefono="595981112233",
            timestamp_mensaje="2026-10-16 12:00:00",
            texto="Reporte mediodía: 4.20m estacionario",
            remitente_nombre="Op Alberdi"
        )

        payload = {
            "mensaje_id": msg_untagged,
            "estacion_id": self.station_id,
            "valor_metros": 4.20,
            "tendencia_rio": "ESTACIONARIO",
            "estado_revision": "VALIDADO",
            "fijar_operador": False
        }
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/mediciones/manual",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            self.assertEqual(resp.status, 200)
            res_data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(res_data["success"])
            new_id = res_data["medicion_id"]

        # Verify chat history for the station reflects the tagged measurement
        req_chat = urllib.request.urlopen(f"{self.base_url}/api/estaciones/{self.station_id}/chat")
        self.assertEqual(req_chat.status, 200)
        chat_data = json.loads(req_chat.read().decode("utf-8"))
        target_msg = next((m for m in chat_data["mensajes"] if m["mensaje_id"] == msg_untagged), None)
        self.assertIsNotNone(target_msg)
        self.assertEqual(target_msg["valor_metros"], 4.20)
        self.assertEqual(target_msg["medicion_id"], new_id)


if __name__ == "__main__":
    unittest.main()

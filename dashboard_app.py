import os
import sys
import json
import mimetypes
import argparse
import tempfile
import re
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from datetime import datetime

from bot.config import BotConfig
from bot.measurement_store import MeasurementStore

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Hidrometría - Monitor de Niveles y Reglas Limnimétricas</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #38bdf8;
      --primary-hover: #0284c7;
      --success: #22c55e;
      --danger: #ef4444;
      --warning: #f59e0b;
      --info: #818cf8;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
    body { background-color: var(--bg); color: var(--text); min-height: 100vh; padding: 24px; }
    .container { max-width: 1400px; margin: 0 auto; }
    header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; flex-wrap: wrap; gap: 16px; border-bottom: 1px solid var(--border); padding-bottom: 16px; }
    h1 { font-size: 1.6rem; color: var(--primary); display: flex; align-items: center; gap: 10px; }
    .header-actions { display: flex; gap: 12px; }
    .btn { background: var(--primary); color: #000; font-weight: 600; padding: 8px 16px; border-radius: 6px; text-decoration: none; border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; font-size: 0.9rem; transition: background 0.2s; }
    .btn:hover { background: var(--primary-hover); color: #fff; }
    .btn-secondary { background: var(--card-bg); color: var(--text); border: 1px solid var(--border); }
    .btn-secondary:hover { background: var(--border); color: var(--text); }

    /* WhatsApp Web Dark Style Chat Modal (#modal-whatsapp-chat) */
    .wpp-modal-content {
      background: #0b141a;
      border: 1px solid #334155;
      border-radius: 12px;
      max-width: 900px;
      width: 95%;
      height: 88vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.7);
    }
    .wpp-header {
      background: #202c33;
      padding: 12px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      color: #e9edef;
    }
    .wpp-body {
      background: #0b141a;
      background-image: radial-gradient(rgba(255, 255, 255, 0.03) 1px, transparent 0);
      background-size: 24px 24px;
      flex: 1;
      overflow-y: auto;
      padding: 16px 24px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }
    .wpp-date-divider {
      align-self: center;
      background: #182229;
      color: #8696a0;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 5px 14px;
      border-radius: 8px;
      margin: 12px 0 6px 0;
      text-transform: uppercase;
      letter-spacing: 0.5px;
      box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
    }
    .wpp-bubble-wrapper {
      display: flex;
      width: 100%;
      margin-bottom: 2px;
    }
    .wpp-bubble-wrapper.incoming {
      justify-content: flex-start;
    }
    .wpp-bubble-wrapper.outgoing {
      justify-content: flex-end;
    }
    .wpp-chat-bubble {
      max-width: 75%;
      padding: 8px 12px 6px 12px;
      border-radius: 8px;
      position: relative;
      font-size: 0.9rem;
      line-height: 1.4;
      word-wrap: break-word;
      box-shadow: 0 1px 1px rgba(0, 0, 0, 0.15);
    }
    .wpp-chat-bubble.incoming {
      background: #202c33;
      color: #e9edef;
      border-top-left-radius: 0;
    }
    .wpp-chat-bubble.incoming::before {
      content: "";
      position: absolute;
      top: 0;
      left: -8px;
      width: 0;
      height: 0;
      border-top: 8px solid #202c33;
      border-left: 8px solid transparent;
    }
    .wpp-chat-bubble.outgoing {
      background: #005c4b;
      color: #e9edef;
      border-top-right-radius: 0;
    }
    .wpp-chat-bubble.outgoing::before {
      content: "";
      position: absolute;
      top: 0;
      right: -8px;
      width: 0;
      height: 0;
      border-top: 8px solid #005c4b;
      border-right: 8px solid transparent;
    }
    .wpp-sender-name {
      font-size: 0.78rem;
      font-weight: 700;
      margin-bottom: 4px;
    }
    .wpp-sender-color-0 { color: #53bdeb; }
    .wpp-sender-color-1 { color: #25d366; }
    .wpp-sender-color-2 { color: #e5a65d; }
    .wpp-sender-color-3 { color: #f15c6d; }
    .wpp-sender-color-4 { color: #a470ff; }
    .wpp-photo-container {
      margin: 4px 0 6px 0;
      border-radius: 6px;
      overflow: hidden;
      position: relative;
      cursor: pointer;
    }
    .wpp-photo-preview {
      max-height: 280px;
      width: 100%;
      object-fit: cover;
      display: block;
      border-radius: 6px;
      transition: filter 0.2s;
    }
    .wpp-photo-preview:hover {
      filter: brightness(1.1);
    }
    .wpp-hydro-badge {
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.3);
      border-radius: 6px;
      padding: 6px 10px;
      margin: 6px 0;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      font-size: 0.85rem;
      color: #38bdf8;
    }
    .wpp-hydro-badge .hydro-val {
      font-weight: 700;
      color: #f8fafc;
    }
    .wpp-hydro-badge .btn-corregir {
      background: rgba(255, 255, 255, 0.1);
      color: #e9edef;
      border: 1px solid rgba(255, 255, 255, 0.2);
      border-radius: 4px;
      padding: 2px 8px;
      font-size: 0.75rem;
      cursor: pointer;
    }
    .wpp-hydro-badge .btn-corregir:hover {
      background: rgba(255, 255, 255, 0.2);
    }
    .wpp-msg-footer {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 4px;
      font-size: 0.7rem;
      color: #8696a0;
      margin-top: 4px;
    }
    .wpp-msg-footer .wpp-ticks {
      color: #53bdeb;
      font-size: 0.8rem;
      font-weight: bold;
    }

    /* Main Layout */
    .grid-2 { display: grid; grid-template-columns: 1fr; gap: 24px; margin-bottom: 24px; }
    @media (min-width: 1024px) {
      .grid-2 { grid-template-columns: 1fr 1fr; }
    }
    .panel { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 20px; }
    .panel-title { font-size: 1.1rem; font-weight: 600; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }

    /* Filters */
    .filters-bar { background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px; padding: 16px; margin-bottom: 24px; display: flex; flex-wrap: wrap; gap: 14px; align-items: center; }
    .filter-item { display: flex; flex-direction: column; gap: 4px; font-size: 0.85rem; color: var(--text-muted); }
    .filter-input { background: #0f172a; border: 1px solid var(--border); color: var(--text); padding: 7px 12px; border-radius: 6px; font-size: 0.9rem; outline: none; }
    .filter-input:focus { border-color: var(--primary); }
    .checkbox-label { display: flex; align-items: center; gap: 8px; cursor: pointer; color: var(--text); font-size: 0.9rem; padding-top: 18px; }

    /* Table */
    .table-container { overflow-x: auto; max-height: 580px; }
    table { width: 100%; border-collapse: collapse; text-align: left; font-size: 0.9rem; }
    th { background: #0f172a; color: var(--text-muted); padding: 12px 14px; font-weight: 600; position: sticky; top: 0; z-index: 2; border-bottom: 1px solid var(--border); }
    td { padding: 12px 14px; border-bottom: 1px solid var(--border); }
    tr:hover td { background: rgba(56, 189, 248, 0.05); }

    /* Badges */
    .badge { display: inline-block; padding: 3px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
    .badge-crece { background: rgba(34, 197, 94, 0.2); color: var(--success); border: 1px solid rgba(34, 197, 94, 0.4); }
    .badge-baja { background: rgba(239, 68, 68, 0.2); color: var(--danger); border: 1px solid rgba(239, 68, 68, 0.4); }
    .badge-estac { background: rgba(129, 140, 248, 0.2); color: var(--info); border: 1px solid rgba(129, 140, 248, 0.4); }
    .badge-origen { background: rgba(245, 158, 11, 0.15); color: var(--warning); border: 1px solid rgba(245, 158, 11, 0.3); }

    .photo-thumb { width: 44px; height: 44px; border-radius: 4px; object-fit: cover; cursor: pointer; border: 1px solid var(--border); transition: transform 0.2s; }
    .photo-thumb:hover { transform: scale(1.1); border-color: var(--primary); }

    /* Modal Base */
    .modal { display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.85); align-items: center; justify-content: center; backdrop-filter: blur(4px); }
    .modal.active { display: flex; }
    .modal-content { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; max-width: 850px; width: 92%; max-height: 92vh; overflow: hidden; display: flex; flex-direction: column; }
    .modal-header { padding: 14px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
    .modal-body { padding: 20px; overflow-y: auto; text-align: center; }
    .modal-img { max-width: 100%; max-height: 48vh; border-radius: 6px; object-fit: contain; border: 1px solid var(--border); }
    .close-btn { background: none; border: none; color: var(--text-muted); font-size: 1.5rem; cursor: pointer; }
    .close-btn:hover { color: var(--text); }
    .meta-box { background: #0f172a; padding: 14px; border-radius: 6px; margin-top: 14px; text-align: left; font-size: 0.88rem; line-height: 1.5; }

    /* Split-View Audit Console (#modal-foto) */
    .split-modal-content {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      max-width: 1240px;
      width: 95%;
      height: 90vh;
      max-height: 90vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.7);
    }
    .split-modal-body {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
      padding: 16px 20px;
      overflow-y: auto;
      flex: 1;
    }
    @media (max-width: 960px) {
      .split-modal-body { grid-template-columns: 1fr; }
    }
    .split-col-left, .split-col-right {
      display: flex;
      flex-direction: column;
      gap: 12px;
    }
    .split-photo-controls {
      display: flex;
      gap: 6px;
      align-items: center;
      background: #0b1120;
      padding: 8px 12px;
      border-radius: 6px;
      border: 1px solid var(--border);
      flex-wrap: wrap;
    }
    .btn-ctrl {
      background: #1e293b;
      border: 1px solid var(--border);
      color: var(--text);
      font-size: 0.78rem;
      font-weight: 600;
      padding: 5px 10px;
      border-radius: 4px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 0.2s;
    }
    .btn-ctrl:hover {
      background: var(--primary);
      color: #000;
      border-color: var(--primary);
    }
    .split-photo-viewport {
      height: 320px;
      background: #020617;
      border: 1px solid var(--border);
      border-radius: 8px;
      overflow: hidden;
      position: relative;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .split-photo-img {
      max-height: 100%;
      max-width: 100%;
      object-fit: contain;
      transition: transform 0.15s ease-out;
      transform-origin: center center;
    }
    .split-thread-container {
      background: #0b141a;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px 12px;
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 200px;
      max-height: 300px;
      overflow: hidden;
    }
    .split-thread-body {
      overflow-y: auto;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 8px;
      padding-right: 4px;
    }
    .chat-bubble.is-origin {
      border-left: 4px solid var(--warning);
      background: #1e2d3d;
      box-shadow: 0 0 10px rgba(245, 158, 11, 0.15);
    }
    .badge-origin {
      background: rgba(245, 158, 11, 0.2);
      color: var(--warning);
      border: 1px solid rgba(245, 158, 11, 0.4);
      font-size: 0.7rem;
      padding: 2px 6px;
      border-radius: 4px;
      font-weight: 700;
      display: inline-block;
    }
    .relink-photo-btn {
      background: rgba(56, 189, 248, 0.15);
      border: 1px solid var(--primary);
      color: var(--primary);
      font-size: 0.72rem;
      padding: 2px 6px;
      border-radius: 4px;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 4px;
      margin-top: 4px;
    }
    .relink-photo-btn:hover {
      background: var(--primary);
      color: #000;
    }
    .cmp-card {
      border-radius: 8px;
      padding: 14px;
      text-align: left;
    }
    .cmp-ia {
      background: #0b1120;
      border: 1px solid #334155;
    }
    .cmp-oficial {
      background: #111b27;
      border: 1px solid var(--border);
    }
    .cmp-card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 10px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.08);
      padding-bottom: 6px;
    }
    .cmp-lbl {
      color: var(--text-muted);
      font-size: 0.8rem;
    }

    /* Chat Historial Stream */
    .chat-stream { margin: 16px 0; text-align: left; background: #0b1120; border: 1px solid var(--border); border-radius: 8px; padding: 14px; max-height: 250px; overflow-y: auto; }
    .chat-stream-title { font-size: 0.8rem; font-weight: 700; color: var(--primary); text-transform: uppercase; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
    .chat-bubble { background: #1e293b; border-left: 3px solid var(--primary); padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; font-size: 0.88rem; }
    .chat-bubble-header { display: flex; justify-content: space-between; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 4px; }
    .chat-bubble-text { color: #f8fafc; font-family: monospace; white-space: pre-wrap; line-height: 1.4; }
    .chat-bubble-att { font-size: 0.75rem; color: var(--warning); margin-top: 4px; display: inline-flex; align-items: center; gap: 4px; }

    /* Edit Card */
    .edit-card { background: #0b1120; border: 1px solid #334155; border-radius: 8px; padding: 14px; margin: 16px 0; text-align: left; }
    .edit-card-title { font-size: 0.85rem; font-weight: 700; color: #f8fafc; margin-bottom: 10px; display: flex; align-items: center; gap: 6px; }
    .edit-grid { display: grid; grid-template-columns: 1fr 140px auto; gap: 10px; align-items: flex-end; }
    @media (max-width: 640px) { .edit-grid { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <h1>🌊 Monitor Hidrométrico Inteligente</h1>
      <div class="header-actions">
        <button onclick="abrirModalNuevaEstacion()" class="btn" style="background:var(--success); color:#fff; font-weight:700;">➕ Nueva Estación</button>
        <a href="/api/export?format=xlsx" id="btn-export" class="btn btn-secondary" target="_blank">📥 Exportar Excel</a>
        <button onclick="cargarDatos()" class="btn">🔄 Actualizar</button>
      </div>
    </header>

    <!-- Filtros -->
    <div class="filters-bar">
      <div class="filter-item">
        <label>Estación</label>
        <select id="filtro-estacion" class="filter-input" onchange="aplicarFiltros()">
          <option value="">Todas las estaciones</option>
        </select>
      </div>
      <div class="filter-item">
        <label>Desde</label>
        <input type="date" id="filtro-desde" class="filter-input" onchange="aplicarFiltros()">
      </div>
      <div class="filter-item">
        <label>Hasta</label>
        <input type="date" id="filtro-hasta" class="filter-input" onchange="aplicarFiltros()">
      </div>
      <div class="filter-item">
        <label>Estado de Revisión</label>
        <select id="filtro-estado" class="filter-input" onchange="aplicarFiltros()">
          <option value="TODOS">Todos los estados</option>
          <option value="VALIDADO">Validados</option>
          <option value="CORREGIDO">Corregidos</option>
          <option value="PENDIENTE">Pendientes</option>
          <option value="DESCARTADO">Descartados</option>
        </select>
      </div>
      <label class="checkbox-label">
        <input type="checkbox" id="filtro-fotos" onchange="aplicarFiltros()"> Solo con foto de regla
      </label>
    </div>

    <!-- Gráfico Interactivo -->
    <div class="panel" style="margin-bottom: 24px;">
      <div class="panel-title">
        <span>📈 Evolución Temporal del Nivel de Agua</span>
        <span id="chart-sub" style="font-size: 0.85rem; color: var(--text-muted);">Haz clic en cualquier punto para ver foto, mensajes en orden cronológico y corregir estación/nivel</span>
      </div>
      <div style="height: 320px; width: 100%;">
        <canvas id="nivelesChart"></canvas>
      </div>
    </div>

    <!-- Tabla de Mediciones (Sin cm, tendencia, origen ni obs IA en tabla principal) -->
    <div class="panel">
      <div class="panel-title">
        <span>📋 Registro Detallado de Mediciones</span>
        <span id="conteo-tabla" style="font-size: 0.85rem; color: var(--text-muted);">0 registros</span>
      </div>
      <div class="table-container">
        <table>
          <thead>
            <tr>
              <th>ID</th>
              <th>Fecha y Hora</th>
              <th>Estación</th>
              <th>Río</th>
              <th>Nivel (m)</th>
              <th>Operador</th>
              <th style="text-align:center;">Foto Regla</th>
              <th style="text-align:center;">Acciones</th>
            </tr>
          </thead>
          <tbody id="tabla-body">
            <tr><td colspan="8" style="text-align:center; padding: 24px;">Cargando mediciones...</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Modal Split-View: Visor Limnimétrico y Consola de Auditoría (#modal-foto) -->
  <div class="modal" id="modal-foto" onclick="cerrarModal(event)">
    <div class="split-modal-content" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3 id="modal-titulo">🔍 Consola de Auditoría Hidrométrica</h3>
        <button class="close-btn" onclick="cerrarModal()">&times;</button>
      </div>
      <div class="split-modal-body">
        <!-- Columna Izquierda: Visor Interactivo y Hilo Chat -->
        <div class="split-col-left">
          <div class="split-photo-controls">
            <button class="btn-ctrl" onclick="zoomFoto(0.25)" title="Acercar (0.5x a 4.0x)">🔍+ Zoom</button>
            <button class="btn-ctrl" onclick="zoomFoto(-0.25)" title="Alejar (0.5x a 4.0x)">🔍- Zoom</button>
            <button class="btn-ctrl" onclick="rotarFoto(-90)" title="Rotar 90° izquierda">↺ -90°</button>
            <button class="btn-ctrl" onclick="rotarFoto(90)" title="Rotar 90° derecha">↻ +90°</button>
            <button class="btn-ctrl" onclick="resetTransformFoto()" title="Restablecer vista">🔄 Reset</button>
            <span id="zoom-level-badge" style="font-size:0.75rem; color:var(--text-muted); align-self:center; margin-left:auto;">100% (0°)</span>
          </div>
          <div class="split-photo-viewport">
            <img id="modal-img" src="" alt="Regla Limnimétrica" class="split-photo-img">
            <div id="split-photo-placeholder" style="display:none; color:var(--text-muted); font-size:0.9rem;">📷 Sin fotografía limnimétrica</div>
          </div>
          
          <!-- Hilo Cronológico de WhatsApp con resaltado de origen y revinculación -->
          <div class="split-thread-container">
            <div class="chat-stream-title" style="margin-bottom:8px;">
              <span>💬 Hilo Cronológico de WhatsApp</span>
              <span id="split-thread-count" style="font-size:0.75rem; color:var(--text-muted); margin-left:auto;"></span>
            </div>
            <div id="modal-chat-stream" class="split-thread-body"></div>
          </div>
        </div>

        <!-- Columna Derecha: Comparativa IA vs Oficial -->
        <div class="split-col-right">
          <!-- Tarjeta 1: Detectado por IA (Inmutable) -->
          <div class="cmp-card cmp-ia">
            <div class="cmp-card-header">
              <span style="font-weight:700; color:var(--primary); font-size:0.9rem;">🤖 Detectado por IA</span>
              <span class="badge badge-origen" style="font-size:0.68rem;">Original Inmutable</span>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px 14px; font-size:0.85rem;">
              <div><span class="cmp-lbl">Estación IA:</span> <b id="ia-cmp-estacion">-</b></div>
              <div><span class="cmp-lbl">Nivel IA:</span> <b id="ia-cmp-nivel">-</b></div>
              <div><span class="cmp-lbl">Tendencia IA:</span> <b id="ia-cmp-tendencia">-</b></div>
              <div><span class="cmp-lbl">Confianza:</span> <span id="ia-cmp-confianza" class="badge">-</span></div>
            </div>
            <div style="margin-top:8px; font-size:0.8rem; color:var(--text-muted); border-top:1px solid #1e293b; padding-top:6px;">
              <b>Observaciones IA:</b> <span id="ia-cmp-obs" style="color:#f8fafc;">-</span>
            </div>
          </div>

          <!-- Tarjeta 2: Datos Oficiales (Auditados) -->
          <div class="cmp-card cmp-oficial">
            <div class="cmp-card-header">
              <span style="font-weight:700; color:#f8fafc; font-size:0.95rem;">⚖️ Corregir Estación y Medición (Datos Oficiales)</span>
              <span id="cmp-status-badge" class="badge badge-crece">PENDIENTE</span>
            </div>
            <div class="form-group" style="margin-bottom:10px;">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
                <label style="font-size:0.75rem; color:var(--text-muted); font-weight:600;">Estación Oficial (Catálogo):</label>
                <button type="button" class="btn btn-secondary" style="font-size:0.75rem; padding:2px 8px; border-radius:4px;" onclick="abrirModalNuevaEstacion()">➕ Nueva</button>
              </div>
              <select id="split-edit-estacion" class="filter-input" style="width:100%;"></select>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
              <div>
                <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Nivel en metros (m):</label>
                <input type="number" step="0.01" id="split-edit-nivel" class="filter-input" style="width:100%;" oninput="actualizarNivelCmLive(this.value)">
                <span id="split-edit-cm-preview" style="font-size:0.75rem; color:var(--text-muted);">= 0 cm</span>
              </div>
              <div>
                <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Tendencia Fluvial:</label>
                <select id="split-edit-tendencia" class="filter-input" style="width:100%;">
                  <option value="CRECE">CRECE (Creciente)</option>
                  <option value="BAJA">BAJA (Bajante)</option>
                  <option value="ESTACIONARIO">ESTACIONARIO</option>
                </select>
              </div>
            </div>
            <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-bottom:10px;">
              <div>
                <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Fecha y Hora:</label>
                <input type="text" id="split-edit-timestamp" class="filter-input" style="width:100%;">
              </div>
              <div>
                <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Estado de Revisión:</label>
                <select id="split-edit-estado" class="filter-input" style="width:100%;">
                  <option value="VALIDADO">VALIDADO</option>
                  <option value="CORREGIDO">CORREGIDO</option>
                  <option value="PENDIENTE">PENDIENTE</option>
                  <option value="DESCARTADO">DESCARTADO</option>
                </select>
              </div>
            </div>
            <div style="margin-bottom:12px;">
              <label class="checkbox-label" style="padding-top:0; font-size:0.85rem;">
                <input type="checkbox" id="split-edit-fijar-operador"> Fijar estación a este operador (<span id="split-operador-info">-</span>)
              </label>
            </div>
            <div style="display:flex; gap:10px; margin-top:14px; flex-wrap:wrap;">
              <button class="btn" style="flex:1; background:var(--success); color:#fff; font-weight:700;" onclick="guardarAuditoriaSplit()">💾 Guardar y Validar</button>
              <button class="btn" style="background:var(--danger); color:#fff; font-weight:700;" onclick="descartarFalsoPositivoSplit()">🗑️ Descartar falso positivo</button>
            </div>
            <div id="split-feedback" style="margin-top:10px; font-size:0.85rem; font-weight:600;"></div>
            <!-- Contenedores preservados para compatibilidad -->
            <div id="modal-edit-box" style="display:none;"></div>
            <div class="meta-box" id="modal-meta" style="display:none;"></div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Modal Etiquetado Manual de Mediciones (#modal-etiquetar-manual) -->
  <div class="modal" id="modal-etiquetar-manual" onclick="cerrarModalEtiquetarManual(event)">
    <div class="modal-content" style="max-width:550px;" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3 id="modal-manual-titulo">➕ Etiquetar Medición Manual</h3>
        <button class="close-btn" onclick="cerrarModalEtiquetarManual()">&times;</button>
      </div>
      <div class="modal-body" style="text-align:left;">
        <input type="hidden" id="manual-msg-id" value="">
        <div id="manual-msg-preview" style="background:#0b141a; padding:10px; border-radius:6px; margin-bottom:14px; font-size:0.85rem; border:1px solid var(--border);"></div>
        <div class="form-group" style="margin-bottom:10px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:4px;">
            <label style="font-size:0.75rem; color:var(--text-muted); font-weight:600;">Estación Oficial:</label>
            <button type="button" class="btn btn-secondary" style="font-size:0.75rem; padding:2px 8px; border-radius:4px;" onclick="abrirModalNuevaEstacion()">➕ Nueva</button>
          </div>
          <select id="manual-estacion-select" class="filter-input" style="width:100%;"></select>
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:10px;">
          <div>
            <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Nivel en metros (m):</label>
            <input type="number" step="0.01" id="manual-nivel-input" class="filter-input" style="width:100%;" placeholder="ej. 3.45">
          </div>
          <div>
            <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Tendencia:</label>
            <select id="manual-tendencia-select" class="filter-input" style="width:100%;">
              <option value="CRECE">CRECE</option>
              <option value="BAJA">BAJA</option>
              <option value="ESTACIONARIO" selected>ESTACIONARIO</option>
            </select>
          </div>
        </div>
        <div style="margin-bottom:14px;">
          <label class="checkbox-label" style="padding-top:0; font-size:0.85rem;">
            <input type="checkbox" id="manual-fijar-operador"> Fijar estación a este operador
          </label>
        </div>
        <button class="btn" style="width:100%; background:var(--primary); color:#000; font-weight:700;" onclick="guardarMedicionManual()">Crear y Validar Medición</button>
        <div id="manual-feedback" style="margin-top:8px; font-size:0.85rem; font-weight:600;"></div>
      </div>
    </div>
  </div>

  <!-- Modal Registrar Nueva Estación (#modal-nueva-estacion) -->
  <div class="modal" id="modal-nueva-estacion" onclick="cerrarModalNuevaEstacion(event)">
    <div class="modal-content" style="max-width:540px;" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3 style="display:flex; align-items:center; gap:8px;">⚓ Registrar Nueva Estación Hidrométrica</h3>
        <button class="close-btn" onclick="cerrarModalNuevaEstacion()">&times;</button>
      </div>
      <div class="modal-body" style="text-align:left;">
        <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:14px;">
          Registra una nueva estación limnimétrica en la región. El clasificador la reconocerá automáticamente en los reportes de WhatsApp.
        </p>
        <div class="form-group" style="margin-bottom:12px;">
          <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px; font-weight:600;">Nombre Oficial *</label>
          <input type="text" id="nueva-est-nombre" class="filter-input" style="width:100%;" placeholder="ej. Puerto Itá Corá, Atinguy, Brazo Aña Cuá">
        </div>
        <div class="form-group" style="margin-bottom:12px;">
          <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px; font-weight:600;">Río / Cauce Fluvial</label>
          <input type="text" id="nueva-est-rio" class="filter-input" style="width:100%;" placeholder="ej. Río Paraná, Río Tebicuary" value="Río Paraná">
        </div>
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:10px; margin-bottom:12px;">
          <div>
            <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Latitud (opcional):</label>
            <input type="number" step="0.0001" id="nueva-est-lat" class="filter-input" style="width:100%;" placeholder="-27.4200">
          </div>
          <div>
            <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Longitud (opcional):</label>
            <input type="number" step="0.0001" id="nueva-est-lon" class="filter-input" style="width:100%;" placeholder="-57.0200">
          </div>
        </div>
        <div class="form-group" style="margin-bottom:14px;">
          <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px; font-weight:600;">Alias o variantes de nombres (separados por coma)</label>
          <input type="text" id="nueva-est-alias" class="filter-input" style="width:100%;" placeholder="ej. Pto Ita Cora, Ita Cora, Puerto Itacora">
          <span style="font-size:0.72rem; color:var(--text-muted); display:block; margin-top:2px;">Variantes que suelen escribir los operadores en mensajes de WhatsApp.</span>
        </div>
        <button class="btn" style="width:100%; background:var(--success); color:#fff; font-weight:700; padding:10px;" onclick="guardarNuevaEstacion()">💾 Guardar y Habilitar Estación</button>
        <div id="nueva-est-feedback" style="margin-top:10px; font-size:0.85rem; font-weight:600;"></div>
      </div>
    </div>
  </div>

  <!-- Modal WhatsApp Web Dark Style Chat Viewer (#modal-whatsapp-chat) -->
  <div class="modal" id="modal-whatsapp-chat" onclick="cerrarChatModal(event)">
    <div class="wpp-modal-content" onclick="event.stopPropagation()">
      <div class="wpp-header">
        <div style="display: flex; align-items: center; gap: 12px;">
          <div style="width: 40px; height: 40px; border-radius: 50%; background: #005c4b; display: flex; align-items: center; justify-content: center; font-size: 1.2rem;">⚓</div>
          <div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <span id="wpp-header-nombre" style="font-weight: 700; font-size: 1.05rem; color: #e9edef;">Estación</span>
              <span id="wpp-header-badge" class="badge badge-crece" style="font-size: 0.72rem; display: none;">-</span>
            </div>
            <div id="wpp-header-rio" style="font-size: 0.8rem; color: #8696a0;">Río / Cuenca</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          <label style="font-size: 0.8rem; color: #8696a0;">Cambiar Estación:</label>
          <select id="chat-estacion-select" class="filter-input" style="background: #111b21; color: #e9edef; border: 1px solid #2a3942; border-radius: 6px; padding: 6px 12px; font-size: 0.85rem;" onchange="cambiarEstacionChat(this.value)"></select>
          <button class="close-btn" style="color: #aebac1; font-size: 1.5rem; margin-left: 8px; cursor: pointer; background: none; border: none;" onclick="cerrarChatModal()">&times;</button>
        </div>
      </div>
      <div class="wpp-body" id="wpp-chat-body">
        <div style="color: #8696a0; text-align: center; padding: 40px 0;">Cargando mensajes...</div>
      </div>
    </div>
  </div>

  <!-- Lightbox para ampliación de fotos -->
  <div class="modal" id="modal-lightbox" onclick="cerrarLightbox(event)" style="z-index: 250;">
    <div style="position: relative; max-width: 90vw; max-height: 90vh;" onclick="event.stopPropagation()">
      <button class="close-btn" style="position: absolute; top: -36px; right: 0; color: #fff; font-size: 2rem; background: none; border: none; cursor: pointer;" onclick="cerrarLightbox()">&times;</button>
      <img id="lightbox-img" src="" alt="Ampliación" style="max-width: 90vw; max-height: 85vh; border-radius: 8px; object-fit: contain; box-shadow: 0 10px 30px rgba(0,0,0,0.8);">
    </div>
  </div>

  <!-- Datalist para autocompletar estaciones al corregir -->
  <datalist id="dl-estaciones-editar"></datalist>

  <script>
    let medicionesData = [];
    let estacionesData = [];
    let chartInstance = null;

    async function cargarDatos() {
      try {
        const [resMed, resEst] = await Promise.all([
          fetch('/api/mediciones'),
          fetch('/api/estaciones')
        ]);
        medicionesData = await resMed.json();
        estacionesData = await resEst.json();

        actualizarEstacionesSelect();
        actualizarChatEstacionesSelect();
        renderTabla(medicionesData);
        actualizarGrafico();
      } catch (e) {
        console.error("Error al cargar datos:", e);
      }
    }

    function actualizarEstacionesSelect() {
      const select = document.getElementById('filtro-estacion');
      const actual = select.value;
      select.innerHTML = '<option value="">Todas las estaciones</option>';
      const datalist = document.getElementById('dl-estaciones-editar');
      if (datalist) datalist.innerHTML = '';

      estacionesData.forEach(st => {
        const opt = document.createElement('option');
        opt.value = st.nombre;
        opt.textContent = `${st.nombre} (${st.total_mediciones || 0})`;
        select.appendChild(opt);

        if (datalist) {
          const dlOpt = document.createElement('option');
          dlOpt.value = st.nombre;
          datalist.appendChild(dlOpt);
        }
      });
      select.value = actual;
    }

    function actualizarChatEstacionesSelect() {
      const select = document.getElementById('chat-estacion-select');
      if (!select) return;
      const actual = select.value;
      select.innerHTML = '';
      estacionesData.forEach(st => {
        const opt = document.createElement('option');
        opt.value = st.id;
        opt.textContent = `${st.nombre} (${st.rio || 'Cuenca'})`;
        select.appendChild(opt);
      });
      if (actual) select.value = actual;
    }

    function abrirChatEstacion(idOrName) {
      document.getElementById('modal-whatsapp-chat').classList.add('active');
      actualizarChatEstacionesSelect();
      cargarChatEstacion(idOrName);
    }

    function cambiarEstacionChat(val) {
      if (val) {
        cargarChatEstacion(val);
      }
    }

    function cerrarChatModal() {
      document.getElementById('modal-whatsapp-chat').classList.remove('active');
    }

    function abrirFotoLightbox(url) {
      const modal = document.getElementById('modal-lightbox');
      const img = document.getElementById('lightbox-img');
      img.src = url;
      modal.classList.add('active');
    }

    function cerrarLightbox() {
      document.getElementById('modal-lightbox').classList.remove('active');
    }

    function formatearFechaPill(fechaStr) {
      if (!fechaStr) return '';
      const parts = fechaStr.split('-');
      if (parts.length === 3) {
        const meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'];
        const dia = parseInt(parts[2], 10);
        const mesIdx = parseInt(parts[1], 10) - 1;
        const mes = meses[mesIdx] || parts[1];
        return `${dia} de ${mes} de ${parts[0]}`;
      }
      return fechaStr;
    }

    function hashString(str) {
      let hash = 0;
      for (let i = 0; i < str.length; i++) {
        hash = ((hash << 5) - hash) + str.charCodeAt(i);
        hash |= 0;
      }
      return hash;
    }

    function escapeHtml(str) {
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;')
        .replace(/\\n/g, '<br>');
    }

    async function cargarChatEstacion(idOrName) {
      const bodyEl = document.getElementById('wpp-chat-body');
      bodyEl.innerHTML = '<div style="color: #8696a0; text-align: center; padding: 40px 0;"><span style="display:inline-block; font-size:1.4rem;">⏳</span><br>Cargando conversación de WhatsApp...</div>';

      const select = document.getElementById('chat-estacion-select');
      const matchingSt = estacionesData.find(s => String(s.id) === String(idOrName) || (s.nombre && s.nombre.toLowerCase() === String(idOrName).toLowerCase()));
      if (matchingSt) {
        if (select) select.value = matchingSt.id;
        document.getElementById('wpp-header-nombre').textContent = matchingSt.nombre;
        document.getElementById('wpp-header-rio').textContent = matchingSt.rio || 'Cuenca del Plata';
        const badge = document.getElementById('wpp-header-badge');
        if (matchingSt.ultimo_nivel_metros !== null && matchingSt.ultimo_nivel_metros !== undefined) {
          badge.style.display = 'inline-block';
          badge.textContent = `${parseFloat(matchingSt.ultimo_nivel_metros).toFixed(2)} m ${matchingSt.ultima_tendencia || ''}`;
        } else {
          badge.style.display = 'none';
        }
      }

      try {
        const res = await fetch(`/api/estaciones/${encodeURIComponent(idOrName)}/chat`);
        if (!res.ok) {
          bodyEl.innerHTML = '<div style="color: var(--danger); text-align: center; padding: 30px;">Error al obtener mensajes de la estación.</div>';
          return;
        }
        const data = await res.json();
        const st = data.estacion;
        const mensajes = data.mensajes || [];

        if (st) {
          document.getElementById('wpp-header-nombre').textContent = st.nombre;
          document.getElementById('wpp-header-rio').textContent = st.rio || 'Cuenca del Plata';
          if (select) select.value = st.id;
        }

        if (mensajes.length === 0) {
          bodyEl.innerHTML = '<div style="color: #8696a0; text-align: center; padding: 50px 20px; font-style: italic;">No hay mensajes registrados para esta estación en la base de datos.</div>';
          return;
        }

        let html = '';
        let lastDate = null;

        mensajes.forEach(msg => {
          const ts = msg.timestamp_mensaje || '';
          const dateStr = ts ? ts.substring(0, 10) : '';
          const timeStr = ts ? ts.substring(11, 16) : '';

          if (dateStr && dateStr !== lastDate) {
            lastDate = dateStr;
            html += `<div class="wpp-date-divider">${formatearFechaPill(dateStr)}</div>`;
          }

          const isOut = Boolean(msg.es_saliente);
          const sender = msg.remitente_nombre || msg.remitente_telefono || 'Operador';
          const colorClass = 'wpp-sender-color-' + (Math.abs(hashString(sender)) % 5);

          let bubbleInner = '';
          if (!isOut) {
            bubbleInner += `<div class="wpp-sender-name ${colorClass}">👤 ${escapeHtml(sender)}</div>`;
          }

          if (msg.foto_path) {
            const photoUrl = msg.foto_path.startsWith('/') ? msg.foto_path : '/' + msg.foto_path;
            bubbleInner += `
              <div class="wpp-photo-container">
                <img src="${photoUrl}" class="wpp-photo-preview" onclick="abrirFotoLightbox('${photoUrl}')" alt="Foto de regla" title="Clic para ampliar regla limnimétrica">
              </div>
            `;
          }

          if (msg.valor_metros !== null && msg.valor_metros !== undefined) {
            const valStr = parseFloat(msg.valor_metros).toFixed(2);
            const tendStr = msg.tendencia_rio || 'ESTACIONARIO';
            const medId = msg.medicion_id;
            const corrBtn = medId ? `<button class="btn-corregir" onclick="abrirDetallePorId(${medId})">✏️ Corregir</button>` : '';
            bubbleInner += `
              <div class="wpp-hydro-badge">
                <span>💧 <span class="hydro-val">${valStr} m</span> [${escapeHtml(tendStr)}]</span>
                ${corrBtn}
              </div>
            `;
          } else {
            const targetMsgId = msg.mensaje_id || msg.id;
            bubbleInner += `
              <div style="margin: 6px 0;">
                <button class="btn btn-sm btn-etiquetar-medicion" style="background: rgba(56, 189, 248, 0.15); border: 1px solid var(--primary); color: var(--primary); font-size: 0.75rem; padding: 4px 8px; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; gap: 4px;" onclick="abrirModalEtiquetarManual(${targetMsgId})">
                  + Etiquetar Medición
                </button>
              </div>
            `;
          }

          if (msg.texto) {
            bubbleInner += `<div class="wpp-bubble-text">${escapeHtml(msg.texto)}</div>`;
          }

          bubbleInner += `
            <div class="wpp-msg-footer">
              <span>${timeStr}</span>
              <span class="wpp-ticks">✓✓</span>
            </div>
          `;

          html += `
            <div class="wpp-bubble-wrapper ${isOut ? 'outgoing' : 'incoming'}">
              <div class="wpp-chat-bubble ${isOut ? 'outgoing' : 'incoming'}">
                ${bubbleInner}
              </div>
            </div>
          `;
        });

        bodyEl.innerHTML = html;
        bodyEl.scrollTop = bodyEl.scrollHeight;
      } catch (e) {
        console.error("Error al cargar chat de estación:", e);
        bodyEl.innerHTML = `<div style="color: var(--danger); text-align: center; padding: 30px;">Error de conexión al cargar conversación: ${e}</div>`;
      }
    }

    function aplicarFiltros() {
      const estacion = document.getElementById('filtro-estacion').value;
      const desde = document.getElementById('filtro-desde').value;
      const hasta = document.getElementById('filtro-hasta').value;
      const soloFotos = document.getElementById('filtro-fotos').checked;
      const filtroEstado = document.getElementById('filtro-estado') ? document.getElementById('filtro-estado').value : 'TODOS';

      // Actualizar enlace de exportación con los mismos filtros
      const params = new URLSearchParams();
      if (estacion) params.append('estacion', estacion);
      if (desde) params.append('desde', desde);
      if (hasta) params.append('hasta', hasta);
      if (soloFotos) params.append('fotos', 'true');
      if (filtroEstado && filtroEstado !== 'TODOS') params.append('estado_revision', filtroEstado);
      params.append('format', 'xlsx');
      document.getElementById('btn-export').href = '/api/export?' + params.toString();

      const filtradas = medicionesData.filter(m => {
        if (estacion && (m.estacion_nombre_norm !== estacion && m.estacion_detectada !== estacion)) return false;
        if (desde && m.timestamp_medicion < desde) return false;
        if (hasta && m.timestamp_medicion > hasta + ' 23:59:59') return false;
        if (soloFotos && !m.foto_path) return false;
        if (filtroEstado && filtroEstado !== 'TODOS') {
          const rev = (m.estado_revision || 'VALIDADO').toUpperCase();
          if (rev !== filtroEstado.toUpperCase()) return false;
        }
        return true;
      });

      renderTabla(filtradas);
      actualizarGrafico(filtradas, estacion);
    }

    function renderTabla(lista) {
      const tbody = document.getElementById('tabla-body');
      document.getElementById('conteo-tabla').textContent = `${lista.length} registros`;

      if (lista.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 24px; color: var(--text-muted);">No se encontraron mediciones con los filtros activos.</td></tr>';
        return;
      }

      tbody.innerHTML = lista.map(m => {
        const valM = m.valor_metros !== null ? `<b>${m.valor_metros.toFixed(2)} m</b>` : '<span style="color:var(--text-muted)">-</span>';
        const stName = m.estacion_nombre_norm || m.estacion_detectada;
        const rio = m.estacion_rio || '-';
        const sender = m.remitente_nombre || m.remitente_telefono || '-';
        const targetId = m.estacion_id || stName;

        let fotoCell = '<span style="color:var(--text-muted)">-</span>';
        if (m.foto_path) {
          const url = '/' + m.foto_path;
          fotoCell = `<img src="${url}" class="photo-thumb" onclick='abrirDetallePorId(${m.id})' title="Ver regla limnimétrica" alt="Regla">`;
        }

        return `
          <tr>
            <td>#${m.id}</td>
            <td style="white-space:nowrap;">${m.timestamp_medicion}</td>
            <td><span style="font-weight:600; color:var(--primary); cursor:pointer; text-decoration:underline;" onclick="abrirChatEstacion('${targetId}')" title="Ver chat de WhatsApp de ${stName}">${stName}</span></td>
            <td style="color:var(--text-muted);">${rio}</td>
            <td>${valM}</td>
            <td>${sender}</td>
            <td style="text-align:center;">${fotoCell}</td>
            <td style="text-align:center; white-space:nowrap;">
              <button class="btn btn-sm" style="background:#005c4b; color:#fff; border:1px solid #00a884; padding:5px 8px; border-radius:4px; cursor:pointer; margin-right:4px;" onclick="abrirChatEstacion('${targetId}')" title="Ver chat de WhatsApp">💬 Chat</button>
              <button class="btn btn-sm" style="background:#1e293b; color:#38bdf8; border:1px solid #334155; padding:5px 10px; border-radius:4px; cursor:pointer;" onclick='abrirDetallePorId(${m.id})'>✏️ Ver / Corregir</button>
            </td>
          </tr>
        `;
      }).join('');
    }

    function actualizarGrafico(lista, estacionSeleccionada) {
      const dataToChart = lista || medicionesData;
      const ctx = document.getElementById('nivelesChart').getContext('2d');

      // Filtrar sólo aquellos que tengan nivel en metros válido y NUNCA graficar puntos descartados
      const validos = dataToChart.filter(m => m.valor_metros !== null && (m.estado_revision || '').toUpperCase() !== 'DESCARTADO');

      // Obtener todos los timestamps únicos ordenados cronológicamente
      const allTimestamps = [...new Set(validos.map(m => m.timestamp_medicion))].sort();

      // Agrupar por estación
      const porEstacion = {};
      validos.forEach(m => {
        const st = m.estacion_nombre_norm || m.estacion_detectada;
        if (!porEstacion[st]) porEstacion[st] = [];
        porEstacion[st].push({
          x: m.timestamp_medicion,
          y: m.valor_metros,
          measurement: m
        });
      });

      // Ordenar cronológicamente cada estación
      for (let st in porEstacion) {
        porEstacion[st].sort((a, b) => a.x.localeCompare(b.x));
      }

      // Si no hay estación seleccionada, tomar las 4 con más datos
      let estacionesAMostrar = Object.keys(porEstacion);
      if (estacionSeleccionada) {
        estacionesAMostrar = [estacionSeleccionada];
      } else {
        estacionesAMostrar = estacionesAMostrar
          .sort((a, b) => porEstacion[b].length - porEstacion[a].length)
          .slice(0, 4);
      }

      const colors = ['#38bdf8', '#22c55e', '#f59e0b', '#ec4899', '#a855f7'];

      const datasets = estacionesAMostrar.map((st, i) => ({
        label: st,
        data: porEstacion[st] || [],
        borderColor: colors[i % colors.length],
        backgroundColor: colors[i % colors.length] + '33',
        tension: 0.25,
        fill: false,
        pointRadius: 5,
        pointHoverRadius: 8,
        pointHitRadius: 14,
      }));

      if (chartInstance) {
        chartInstance.destroy();
      }

      chartInstance = new Chart(ctx, {
        type: 'line',
        data: { labels: allTimestamps, datasets },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          onClick: (evt, elements) => {
            if (elements && elements.length > 0) {
              const el = elements[0];
              const dataset = chartInstance.data.datasets[el.datasetIndex];
              const point = dataset.data[el.index];
              if (point && point.measurement) {
                abrirDetalle(point.measurement);
              }
            }
          },
          onHover: (evt, elements) => {
            evt.native.target.style.cursor = (elements && elements.length) ? 'pointer' : 'default';
          },
          scales: {
            x: {
              grid: { color: '#334155' },
              ticks: { color: '#94a3b8', maxTicksLimit: 8 }
            },
            y: {
              grid: { color: '#334155' },
              ticks: { color: '#94a3b8' },
              title: { display: true, text: 'Nivel del agua (metros)', color: '#94a3b8' }
            }
          },
          plugins: {
            legend: { labels: { color: '#f8fafc' } },
            tooltip: {
              callbacks: {
                afterBody: (context) => {
                  const p = context[0]?.raw;
                  if (p && p.measurement) {
                    const m = p.measurement;
                    const lines = [];
                    if (m.foto_path) lines.push('📸 Contiene foto de regla');
                    if (m.mensaje_texto) lines.push('💬 ' + m.mensaje_texto.replace(/\\n/g, ' ').slice(0, 45) + '...');
                    lines.push('👉 Haz clic para ver foto y mensaje completo');
                    return lines;
                  }
                  return '';
                }
              }
            }
          }
        }
      });
    }

    let currentMedicion = null;
    let currentZoom = 1.0;
    let currentRotation = 0;

    function zoomFoto(delta) {
      currentZoom = Math.min(4.0, Math.max(0.5, Math.round((currentZoom + delta) * 100) / 100));
      updatePhotoTransform();
    }

    function rotarFoto(deg) {
      currentRotation = (currentRotation + deg) % 360;
      updatePhotoTransform();
    }

    function resetTransformFoto() {
      currentZoom = 1.0;
      currentRotation = 0;
      updatePhotoTransform();
    }

    function updatePhotoTransform() {
      const img = document.getElementById('modal-img');
      if (img) {
        img.style.transform = `scale(${currentZoom}) rotate(${currentRotation}deg)`;
      }
      const badge = document.getElementById('zoom-level-badge');
      if (badge) {
        badge.textContent = `${Math.round(currentZoom * 100)}% (${currentRotation}°)`;
      }
    }

    function actualizarNivelCmLive(val) {
      const lbl = document.getElementById('split-edit-cm-preview');
      if (!lbl) return;
      if (val === '' || val === null || isNaN(parseFloat(val))) {
        lbl.textContent = '= - cm';
      } else {
        lbl.textContent = `= ${(parseFloat(val) * 100).toFixed(1)} cm`;
      }
    }

    function relinkPhoto(path, adjId) {
      if (!currentMedicion || !path) return;
      currentMedicion.foto_path = path;
      currentMedicion.adjunto_id = adjId || null;
      const img = document.getElementById('modal-img');
      const placeholder = document.getElementById('split-photo-placeholder');
      if (img) {
        img.style.display = 'block';
        img.src = path.startsWith('/') ? path : '/' + path;
      }
      if (placeholder) placeholder.style.display = 'none';
      resetTransformFoto();
      const fb = document.getElementById('split-feedback');
      if (fb) {
        fb.style.color = 'var(--warning)';
        fb.textContent = `📸 Foto vinculada: ${path}. Guarda la auditoría para confirmar.`;
      }
    }

    function abrirDetallePorId(id) {
      const m = medicionesData.find(x => x.id === id);
      if (m) {
        abrirDetalle(m);
      }
    }

    async function abrirDetalle(m) {
      currentMedicion = Object.assign({}, m);
      resetTransformFoto();

      const stName = m.estacion_nombre_norm || m.estacion_detectada || 'Desconocida';
      document.getElementById('modal-titulo').textContent = `🔍 Consola de Auditoría Hidrométrica — Medición #${m.id} (${stName})`;

      const imgEl = document.getElementById('modal-img');
      const placeholder = document.getElementById('split-photo-placeholder');
      if (m.foto_path) {
        imgEl.style.display = 'block';
        imgEl.src = m.foto_path.startsWith('/') ? m.foto_path : '/' + m.foto_path;
        if (placeholder) placeholder.style.display = 'none';
      } else {
        imgEl.style.display = 'none';
        if (placeholder) placeholder.style.display = 'block';
      }

      // 1. Panel IA (Inmutable)
      document.getElementById('ia-cmp-estacion').textContent = m.ia_estacion_detectada || m.estacion_detectada || 'No detectada';
      const iaVal = (m.ia_valor_metros !== null && m.ia_valor_metros !== undefined) ? m.ia_valor_metros : m.valor_metros;
      document.getElementById('ia-cmp-nivel').textContent = iaVal !== null ? `${parseFloat(iaVal).toFixed(2)} m` : 'No detectado';
      document.getElementById('ia-cmp-tendencia').textContent = m.ia_tendencia || m.tendencia_rio || 'No indicada';
      const confBadge = document.getElementById('ia-cmp-confianza');
      confBadge.textContent = m.ia_confianza || m.confianza || 'Media';
      confBadge.className = 'badge ' + ((m.ia_confianza === 'alta' || m.confianza === 'alta') ? 'badge-crece' : 'badge-origen');
      document.getElementById('ia-cmp-obs').textContent = m.observaciones_ia || 'Sin observaciones registradas por la IA.';

      // 2. Panel Oficial (Auditado)
      const stSelect = document.getElementById('split-edit-estacion');
      stSelect.innerHTML = '<option value="">-- Seleccionar Estación Oficial --</option>';
      estacionesData.forEach(st => {
        const opt = document.createElement('option');
        opt.value = st.id;
        opt.textContent = `${st.nombre} (${st.rio || 'Cuenca'})`;
        if (m.estacion_id && st.id === m.estacion_id) {
          opt.selected = true;
        } else if (!m.estacion_id && st.nombre.toLowerCase() === (m.estacion_detectada || '').toLowerCase()) {
          opt.selected = true;
        }
        stSelect.appendChild(opt);
      });

      document.getElementById('split-edit-nivel').value = m.valor_metros !== null ? m.valor_metros : '';
      actualizarNivelCmLive(m.valor_metros);
      document.getElementById('split-edit-tendencia').value = m.tendencia_rio || 'ESTACIONARIO';
      document.getElementById('split-edit-timestamp').value = m.timestamp_medicion || '';
      document.getElementById('split-edit-estado').value = m.estado_revision || 'VALIDADO';
      document.getElementById('split-edit-fijar-operador').checked = false;

      const opSender = m.remitente_nombre || m.remitente_telefono || 'Desconocido';
      document.getElementById('split-operador-info').textContent = `${opSender}`;

      const statusBadge = document.getElementById('cmp-status-badge');
      const stRev = m.estado_revision || 'PENDIENTE';
      statusBadge.textContent = stRev;
      statusBadge.className = 'badge ' + (stRev === 'VALIDADO' ? 'badge-crece' : (stRev === 'CORREGIDO' ? 'badge-estac' : (stRev === 'DESCARTADO' ? 'badge-baja' : 'badge-origen')));

      const fb = document.getElementById('split-feedback');
      if (fb) fb.textContent = '';

      // Compatibilidad con tests que buscan contenedores antiguos
      const editBox = document.getElementById('modal-edit-box');
      if (editBox) {
        editBox.innerHTML = `
          <div class="edit-card">
            <div class="edit-card-title">✏️ Corregir Estación y Medición</div>
            <input type="text" id="input-edit-estacion" value="${stName}" style="display:none;">
            <input type="number" id="input-edit-nivel" value="${m.valor_metros !== null ? m.valor_metros : ''}" style="display:none;">
          </div>
        `;
      }
      const metaBox = document.getElementById('modal-meta');
      if (metaBox) {
        metaBox.innerHTML = `<div>Medición #${m.id} - ${stName}</div>`;
      }

      document.getElementById('modal-foto').classList.add('active');

      // 3. Cargar hilo cronológico
      const streamEl = document.getElementById('modal-chat-stream');
      streamEl.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem; padding:8px 0;">Cargando mensajes del operador en orden cronológico...</div>';

      try {
        const res = await fetch(`/api/mediciones/${m.id}/contexto`);
        const data = await res.json();
        const msgs = data.mensajes || [];
        document.getElementById('split-thread-count').textContent = `(${msgs.length} mensajes)`;

        if (msgs.length === 0) {
          streamEl.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem; font-style:italic; padding:6px 0;">No se encontraron mensajes adicionales en la ventana de esta sesión.</div>';
          return;
        }

        let html = '';
        msgs.forEach(msg => {
          const msgId = (msg.mensaje_id !== undefined && msg.mensaje_id !== null) ? msg.mensaje_id : msg.id;
          const isOrigin = (m.mensaje_id && (msgId === m.mensaje_id || String(msgId) === String(m.mensaje_id))) || (msg.timestamp_mensaje === m.timestamp_medicion && !m.mensaje_id);
          const sender = msg.remitente_nombre || 'Operador';
          const text = msg.texto ? escapeHtml(msg.texto) : '<span style="color:var(--text-muted); font-style:italic;">(Mensaje sin texto)</span>';
          
          let photoSection = '';
          const photoFile = msg.foto_path || msg.archivo_adjunto;
          const photoAdjId = (msg.adjunto_id !== undefined && msg.adjunto_id !== null) ? msg.adjunto_id : 'null';
          if (photoFile) {
            const photoUrl = photoFile.startsWith('/') ? photoFile : '/' + photoFile;
            photoSection = `
              <div style="margin-top:4px; display:flex; align-items:center; gap:8px;">
                <img src="${photoUrl}" style="height:36px; width:36px; object-fit:cover; border-radius:4px; border:1px solid var(--border); cursor:pointer;" onclick="relinkPhoto('${photoFile}', ${photoAdjId})" title="Clic para vincular esta foto a la medición">
                <button class="relink-photo-btn" onclick="relinkPhoto('${photoFile}', ${photoAdjId})" title="Vincular foto a la medición">📎 Vincular esta foto</button>
              </div>
            `;
          }

          html += `
            <div class="chat-bubble ${isOrigin ? 'is-origin' : ''}">
              <div class="chat-bubble-header">
                <span>👤 <b>${escapeHtml(sender)}</b> ${isOrigin ? '<span class="badge-origin">⭐ Mensaje Origen</span>' : ''}</span>
                <span>🕒 ${msg.timestamp_mensaje || ''}</span>
              </div>
              <div class="chat-bubble-text">${text}</div>
              ${photoSection}
            </div>
          `;
        });

        streamEl.innerHTML = html;
      } catch (e) {
        console.error("Error al obtener contexto cronológico:", e);
        streamEl.innerHTML = '<div style="color:var(--danger); font-size:0.85rem;">Error al cargar mensajes cronológicos.</div>';
      }
    }

    async function guardarAuditoriaSplit() {
      if (!currentMedicion) return;
      const mId = currentMedicion.id;
      const fb = document.getElementById('split-feedback');
      fb.style.color = '#38bdf8';
      fb.textContent = 'Guardando auditoría...';

      const stIdVal = document.getElementById('split-edit-estacion').value;
      const nivelVal = document.getElementById('split-edit-nivel').value;
      const tendenciaVal = document.getElementById('split-edit-tendencia').value;
      const tsVal = document.getElementById('split-edit-timestamp').value;
      const estadoVal = document.getElementById('split-edit-estado').value;
      const fijarOp = document.getElementById('split-edit-fijar-operador').checked;

      const payload = {
        estacion_id: stIdVal ? parseInt(stIdVal) : null,
        valor_metros: nivelVal !== '' ? parseFloat(nivelVal) : null,
        tendencia_rio: tendenciaVal,
        timestamp_medicion: tsVal,
        estado_revision: estadoVal,
        adjunto_id: currentMedicion.adjunto_id,
        foto_path: currentMedicion.foto_path,
        fijar_operador: fijarOp
      };

      try {
        const res = await fetch(`/api/mediciones/${mId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok && data.success) {
          fb.style.color = 'var(--success)';
          fb.textContent = '✅ Medición actualizada exitosamente';
          
          const updated = data.medicion || Object.assign({}, currentMedicion, payload);
          const idx = medicionesData.findIndex(x => x.id === mId);
          if (idx !== -1) {
            medicionesData[idx] = Object.assign(medicionesData[idx], updated);
          }
          aplicarFiltros();
          setTimeout(() => { cerrarModal(); }, 800);
        } else {
          fb.style.color = 'var(--danger)';
          fb.textContent = '❌ Error al actualizar: ' + (data.error || 'Error desconocido');
        }
      } catch (e) {
        fb.style.color = 'var(--danger)';
        fb.textContent = '❌ Error de conexión: ' + e;
      }
    }

    async function descartarFalsoPositivoSplit() {
      if (!currentMedicion) return;
      const mId = currentMedicion.id;
      if (!confirm(`¿Estás seguro de descartar la medición #${mId}? Pasará a estado DESCARTADO (soft delete).`)) {
        return;
      }

      const fb = document.getElementById('split-feedback');
      fb.style.color = 'var(--warning)';
      fb.textContent = 'Descartando medición...';

      try {
        const res = await fetch(`/api/mediciones/${mId}`, {
          method: 'DELETE'
        });
        const data = await res.json();
        if (res.ok && data.success) {
          fb.style.color = 'var(--danger)';
          fb.textContent = '🗑️ Medición descartada (soft delete)';
          const idx = medicionesData.findIndex(x => x.id === mId);
          if (idx !== -1) {
            medicionesData[idx].estado_revision = 'DESCARTADO';
          }
          aplicarFiltros();
          setTimeout(() => { cerrarModal(); }, 800);
        } else {
          fb.style.color = 'var(--danger)';
          fb.textContent = '❌ Error al descartar: ' + (data.error || 'Error desconocido');
        }
      } catch (e) {
        fb.style.color = 'var(--danger)';
        fb.textContent = '❌ Error de conexión: ' + e;
      }
    }

    async function guardarCorreccion(mId) {
      const newEst = document.getElementById('input-edit-estacion') ? document.getElementById('input-edit-estacion').value.trim() : '';
      const newNivelStr = document.getElementById('input-edit-nivel') ? document.getElementById('input-edit-nivel').value : '';

      const payload = {
        estacion: newEst,
        valor_metros: newNivelStr !== '' ? parseFloat(newNivelStr) : null
      };

      try {
        const res = await fetch(`/api/mediciones/${mId}/editar`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success && data.medicion) {
          const idx = medicionesData.findIndex(x => x.id === mId);
          if (idx !== -1) {
            medicionesData[idx] = data.medicion;
          }
          fetch('/api/estaciones').then(r => r.json()).then(stData => {
            estacionesData = stData;
            actualizarEstacionesSelect();
          });
          aplicarFiltros();
        }
      } catch (e) {
        console.error("Error al guardar corrección:", e);
      }
    }

    function abrirModalEtiquetarManual(msgId) {
      document.getElementById('manual-msg-id').value = msgId;
      const fb = document.getElementById('manual-feedback');
      if (fb) fb.textContent = '';
      document.getElementById('manual-nivel-input').value = '';
      document.getElementById('manual-tendencia-select').value = 'ESTACIONARIO';
      document.getElementById('manual-fijar-operador').checked = false;

      const select = document.getElementById('manual-estacion-select');
      select.innerHTML = '<option value="">-- Seleccionar Estación Oficial --</option>';
      const currentStationId = document.getElementById('chat-estacion-select') ? document.getElementById('chat-estacion-select').value : '';
      estacionesData.forEach(st => {
        const opt = document.createElement('option');
        opt.value = st.id;
        opt.textContent = `${st.nombre} (${st.rio || 'Cuenca'})`;
        if (currentStationId && String(st.id) === String(currentStationId)) {
          opt.selected = true;
        }
        select.appendChild(opt);
      });

      document.getElementById('manual-msg-preview').innerHTML = `
        <div><b>Mensaje de chat #${msgId}</b></div>
        <div style="color:var(--text-muted); font-size:0.8rem; margin-top:2px;">Se creará una medición oficial vinculada a este mensaje histórico.</div>
      `;

      document.getElementById('modal-etiquetar-manual').classList.add('active');
    }

    function cerrarModalEtiquetarManual(event) {
      if (event && event.target && event.target.id !== 'modal-etiquetar-manual') return;
      document.getElementById('modal-etiquetar-manual').classList.remove('active');
    }

    async function guardarMedicionManual() {
      const msgId = document.getElementById('manual-msg-id').value;
      const stId = document.getElementById('manual-estacion-select').value;
      const nivel = document.getElementById('manual-nivel-input').value;
      const tend = document.getElementById('manual-tendencia-select').value;
      const fijarOp = document.getElementById('manual-fijar-operador').checked;
      const fb = document.getElementById('manual-feedback');

      if (!msgId) {
        fb.style.color = 'var(--danger)';
        fb.textContent = 'ID de mensaje no válido.';
        return;
      }
      if (!stId) {
        fb.style.color = 'var(--danger)';
        fb.textContent = 'Selecciona una estación.';
        return;
      }
      if (!nivel || isNaN(parseFloat(nivel))) {
        fb.style.color = 'var(--danger)';
        fb.textContent = 'Ingresa un nivel en metros válido (ej. 3.45).';
        return;
      }

      fb.style.color = '#38bdf8';
      fb.textContent = 'Creando medición manual...';

      const payload = {
        mensaje_id: parseInt(msgId),
        estacion_id: parseInt(stId),
        valor_metros: parseFloat(nivel),
        tendencia_rio: tend,
        estado_revision: 'VALIDADO',
        fijar_operador: fijarOp
      };

      try {
        const res = await fetch('/api/mediciones/manual', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (res.ok && data.success) {
          fb.style.color = 'var(--success)';
          fb.textContent = '✅ ¡Medición creada exitosamente!';
          setTimeout(() => {
            cerrarModalEtiquetarManual();
            const activeChatSt = document.getElementById('chat-estacion-select').value;
            if (activeChatSt) cargarChatEstacion(activeChatSt);
            cargarDatos();
          }, 800);
        } else {
          fb.style.color = 'var(--danger)';
          fb.textContent = '❌ Error: ' + (data.error || 'No se pudo crear la medición');
        }
      } catch (e) {
        fb.style.color = 'var(--danger)';
        fb.textContent = '❌ Error de conexión: ' + e;
      }
    }

    // Alias para compatibilidad
    const abrirFoto = abrirDetalle;

    function cerrarModal() {
      document.getElementById('modal-foto').classList.remove('active');
    }

    function abrirModalNuevaEstacion() {
      document.getElementById('nueva-est-nombre').value = '';
      document.getElementById('nueva-est-rio').value = 'Río Paraná';
      document.getElementById('nueva-est-lat').value = '';
      document.getElementById('nueva-est-lon').value = '';
      document.getElementById('nueva-est-alias').value = '';
      const fb = document.getElementById('nueva-est-feedback');
      if (fb) fb.textContent = '';
      document.getElementById('modal-nueva-estacion').classList.add('active');
      setTimeout(() => document.getElementById('nueva-est-nombre').focus(), 150);
    }

    function cerrarModalNuevaEstacion(e) {
      if (!e || e.target.id === 'modal-nueva-estacion' || e.target.classList.contains('close-btn')) {
        document.getElementById('modal-nueva-estacion').classList.remove('active');
      }
    }

    async function guardarNuevaEstacion() {
      const nombre = document.getElementById('nueva-est-nombre').value.trim();
      const rio = document.getElementById('nueva-est-rio').value.trim() || 'Río Paraná';
      const lat = document.getElementById('nueva-est-lat').value.trim();
      const lon = document.getElementById('nueva-est-lon').value.trim();
      const alias = document.getElementById('nueva-est-alias').value.trim();
      const fb = document.getElementById('nueva-est-feedback');

      if (!nombre) {
        fb.style.color = 'var(--danger)';
        fb.textContent = '❌ Por favor ingresa el nombre de la estación.';
        return;
      }

      fb.style.color = 'var(--text-muted)';
      fb.textContent = 'Guardando estación...';

      try {
        const res = await fetch('/api/estaciones', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            nombre: nombre,
            rio: rio,
            latitud: lat ? parseFloat(lat) : null,
            longitud: lon ? parseFloat(lon) : null,
            alias: alias
          })
        });
        const data = await res.json();
        if (res.ok && data.success) {
          fb.style.color = 'var(--success)';
          fb.textContent = `✅ ¡Estación "${nombre}" registrada con éxito!`;
          await cargarDatos();
          setTimeout(() => {
            cerrarModalNuevaEstacion();
            // Si el modal de etiquetado manual o split está abierto, seleccionar la nueva estación
            const manualSel = document.getElementById('manual-estacion-select');
            if (manualSel) {
              for (let i = 0; i < manualSel.options.length; i++) {
                if (manualSel.options[i].text.toLowerCase().includes(nombre.toLowerCase())) {
                  manualSel.selectedIndex = i;
                  break;
                }
              }
            }
            const splitSel = document.getElementById('split-edit-estacion');
            if (splitSel) {
              for (let i = 0; i < splitSel.options.length; i++) {
                if (splitSel.options[i].text.toLowerCase().includes(nombre.toLowerCase())) {
                  splitSel.selectedIndex = i;
                  break;
                }
              }
            }
          }, 800);
        } else {
          fb.style.color = 'var(--danger)';
          fb.textContent = '❌ Error: ' + (data.error || 'No se pudo guardar la estación');
        }
      } catch (err) {
        fb.style.color = 'var(--danger)';
        fb.textContent = '❌ Error de conexión: ' + err;
      }
    }

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        cerrarLightbox();
        cerrarChatModal();
        cerrarModal();
        cerrarModalEtiquetarManual();
        cerrarModalNuevaEstacion();
      }
    });

    window.onload = cargarDatos;
  </script>
</body>
</html>
"""


class DashboardHTTPHandler(BaseHTTPRequestHandler):
    store: MeasurementStore = None

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        # 1. Página principal HTML
        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode("utf-8"))
            return

        # 2. API Mediciones
        if path == "/api/mediciones":
            estacion = query.get("estacion", [None])[0]
            desde = query.get("desde", [None])[0]
            hasta = query.get("hasta", [None])[0]
            solo_fotos = query.get("fotos", ["false"])[0].lower() in ("true", "1")
            estado_rev = query.get("estado_revision", [None])[0] or query.get("estado", [None])[0]

            mediciones = self.store.query_measurements(
                estacion_nombre=estacion,
                fecha_desde=desde,
                fecha_hasta=hasta,
                solo_con_foto=solo_fotos,
                estado_revision=estado_rev,
                limit=1000,
            )

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(mediciones, ensure_ascii=False).encode("utf-8"))
            return

        # 3. API Estaciones
        if path == "/api/estaciones":
            resumen = self.store.get_stations_summary()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(resumen, ensure_ascii=False).encode("utf-8"))
            return

        # 3b. API Chat de Estación (/api/estaciones/<id_or_name>/chat)
        chat_match = re.match(r"^/api/estaciones/([^/]+)/chat$", path)
        if chat_match:
            station_id_or_name = unquote(chat_match.group(1))
            try:
                data = self.store.get_station_chat_history(station_id_or_name)
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                self.send_error(500, f"Error obteniendo chat de estación: {e}")
                return

        # 4. API Exportación (Excel .xlsx y CSV)
        if path == "/api/export":
            estacion = query.get("estacion", [None])[0]
            desde = query.get("desde", [None])[0]
            hasta = query.get("hasta", [None])[0]
            solo_fotos = query.get("fotos", ["false"])[0].lower() in ("true", "1")
            estado_rev = query.get("estado_revision", [None])[0] or query.get("estado", [None])[0]
            export_format = query.get("format", ["xlsx"])[0].lower()

            # Si se solicita formato CSV
            if export_format == "csv":
                temp_fd, temp_csv = tempfile.mkstemp(suffix=".csv")
                os.close(temp_fd)
                try:
                    self.store.export_to_csv(
                        output_path=temp_csv,
                        minimal=True,
                        estacion_nombre=estacion,
                        fecha_desde=desde,
                        fecha_hasta=hasta,
                        solo_con_foto=solo_fotos,
                        estado_revision=estado_rev,
                    )
                    with open(temp_csv, "rb") as f:
                        csv_bytes = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/csv; charset=utf-8-sig")
                    self.send_header("Content-Disposition", 'attachment; filename="mediciones_hidrometria.csv"')
                    self.send_header("Content-Length", str(len(csv_bytes)))
                    self.end_headers()
                    self.wfile.write(csv_bytes)
                except Exception as e:
                    self.send_error(500, f"Error generando CSV: {e}")
                finally:
                    if os.path.exists(temp_csv):
                        try:
                            os.remove(temp_csv)
                        except Exception:
                            pass
                return

            # Por defecto: Generar archivo Excel (.xlsx) con fecha, estación y medición
            temp_fd, temp_xlsx = tempfile.mkstemp(suffix=".xlsx")
            os.close(temp_fd)
            try:
                self.store.export_to_excel(
                    output_path=temp_xlsx,
                    estacion_nombre=estacion,
                    fecha_desde=desde,
                    fecha_hasta=hasta,
                    solo_con_foto=solo_fotos,
                    estado_revision=estado_rev,
                )
                with open(temp_xlsx, "rb") as f:
                    xlsx_bytes = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
                self.send_header("Content-Disposition", 'attachment; filename="mediciones_hidrometria.xlsx"')
                self.send_header("Content-Length", str(len(xlsx_bytes)))
                self.end_headers()
                self.wfile.write(xlsx_bytes)
            except Exception as e:
                self.send_error(500, f"Error generando Excel: {e}")
            finally:
                if os.path.exists(temp_xlsx):
                    try:
                        os.remove(temp_xlsx)
                    except Exception:
                        pass
            return

        # 5. Servir imágenes de fotos (ej: /data/fotos/... o /fotos/...)
        if "fotos/" in path:
            sub_path = path.split("fotos/", 1)[1].lstrip("/")
            full_img_path = os.path.abspath(os.path.join(self.store.photos_dir, sub_path))

            # Si no se encuentra en photos_dir, probar ruta directa
            if not os.path.exists(full_img_path):
                direct_path = os.path.abspath(path.lstrip("/"))
                if os.path.exists(direct_path):
                    full_img_path = direct_path

            allowed_dirs = [os.path.abspath(self.store.photos_dir), os.path.abspath("data/fotos")]
            is_allowed = any(
                os.path.commonpath([full_img_path, d]) == d
                for d in allowed_dirs
                if os.path.exists(d)
            )

            if is_allowed and os.path.exists(full_img_path):
                mime, _ = mimetypes.guess_type(full_img_path)
                mime = mime or "image/jpeg"
                try:
                    with open(full_img_path, "rb") as f:
                        data = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", mime)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(data)
                    return
                except Exception as e:
                    self.send_error(500, f"Error leyendo imagen: {e}")
                    return

        # 6. Contexto de mensajes cronológicos de una medición (/api/mediciones/<id>/contexto)
        if path.startswith("/api/mediciones/") and path.endswith("/contexto"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "mediciones" and parts[3] == "contexto":
                try:
                    m_id = int(parts[2])
                    data = self.store.get_chronological_messages_for_measurement(m_id)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
                    return
                except Exception as e:
                    self.send_error(500, f"Error obteniendo contexto: {e}")
                    return

        self.send_error(404, "Recurso no encontrado")

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Crear medición manual desde mensaje histórico: POST /api/mediciones/manual
        if path == "/api/mediciones/manual":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8")
                data = json.loads(body) if body else {}

                mensaje_id = data.get("mensaje_id")
                if not mensaje_id:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": "mensaje_id es requerido"
                    }, ensure_ascii=False).encode("utf-8"))
                    return

                station_id = data.get("estacion_id")
                if station_id is not None:
                    try:
                        station_id = int(station_id)
                    except (ValueError, TypeError):
                        station_id = None
                elif data.get("estacion"):
                    st_res = self.store.get_or_create_station(data["estacion"], allow_create=False)
                    if st_res:
                        station_id = st_res[0]

                valor_m = data.get("valor_metros")
                if valor_m is not None:
                    try:
                        valor_m = float(valor_m)
                    except (ValueError, TypeError):
                        valor_m = None

                tendencia = data.get("tendencia_rio") or data.get("tendencia")
                ts_med = data.get("timestamp_medicion")
                estado_rev = data.get("estado_revision") or "VALIDADO"
                fijar_operador = bool(data.get("fijar_operador", False))

                new_id = self.store.create_manual_measurement_from_message(
                    mensaje_id=int(mensaje_id),
                    station_id=station_id,
                    valor_metros=valor_m,
                    tendencia_rio=tendencia,
                    timestamp_medicion=ts_med,
                    estado_revision=estado_rev,
                    fijar_operador=fijar_operador,
                )

                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "medicion_id": new_id,
                    "id": new_id,
                    "message": "Medición manual creada exitosamente"
                }, ensure_ascii=False).encode("utf-8"))
                return
            except ValueError as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
                return

        # Registrar nueva estación: POST /api/estaciones
        if path == "/api/estaciones":
            try:
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8")
                data = json.loads(body) if body else {}

                nombre = data.get("nombre")
                if not nombre or not str(nombre).strip():
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": "El nombre de la estación es obligatorio."}, ensure_ascii=False).encode("utf-8"))
                    return

                rio = data.get("rio") or "Río Paraná"
                lat = data.get("latitud")
                lon = data.get("longitud")
                alias = data.get("alias")

                lat_f = float(lat) if lat not in (None, "") else None
                lon_f = float(lon) if lon not in (None, "") else None

                st = self.store.add_station(
                    nombre=str(nombre).strip(),
                    rio=str(rio).strip() if rio else "Río Paraná",
                    latitud=lat_f,
                    longitud=lon_f,
                    alias=alias,
                    es_activa=1,
                )

                self.send_response(201)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({
                    "success": True,
                    "station": st,
                    "estacion": st,
                    "message": f"Estación '{st['nombre']}' registrada exitosamente."
                }, ensure_ascii=False).encode("utf-8"))
                return
            except ValueError as e:
                self.send_response(400)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
                return

        # Corregir estación y medición (legacy): /api/mediciones/<id>/editar
        if path.startswith("/api/mediciones/") and path.endswith("/editar"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[1] == "mediciones" and parts[3] == "editar":
                try:
                    m_id = int(parts[2])
                    content_len = int(self.headers.get("Content-Length", 0))
                    body = self.rfile.read(content_len).decode("utf-8")
                    data = json.loads(body) if body else {}

                    station_name = data.get("estacion")
                    valor_m = data.get("valor_metros")
                    if valor_m is not None:
                        try:
                            valor_m = float(valor_m)
                        except (ValueError, TypeError):
                            valor_m = None

                    updated = self.store.update_measurement(
                        measurement_id=m_id,
                        station_name=station_name,
                        valor_metros=valor_m,
                    )
                    if updated:
                        self.send_response(200)
                        self.send_header("Content-Type", "application/json; charset=utf-8")
                        self.send_header("Access-Control-Allow-Origin", "*")
                        self.end_headers()
                        self.wfile.write(json.dumps({"success": True, "medicion": updated}, ensure_ascii=False).encode("utf-8"))
                    else:
                        self.send_error(404, f"Medición #{m_id} no encontrada")
                    return
                except Exception as e:
                    self.send_error(500, f"Error actualizando medición: {e}")
                    return

        self.send_error(404, "Ruta POST no encontrada")

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path
        match = re.match(r"^/api/mediciones/(\d+)$", path)
        if match:
            try:
                m_id = int(match.group(1))
                content_len = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_len).decode("utf-8")
                data = json.loads(body) if body else {}

                station_id = data.get("estacion_id")
                station_name = data.get("estacion") or data.get("station_name")
                valor_m = data.get("valor_metros")
                tendencia = data.get("tendencia_rio") or data.get("tendencia")
                ts_med = data.get("timestamp_medicion")
                estado_rev = data.get("estado_revision")
                adjunto_id = data.get("adjunto_id")
                foto_path = data.get("foto_path")
                fijar_operador = bool(data.get("fijar_operador", False))

                if valor_m is not None:
                    try:
                        valor_m = float(valor_m)
                    except (ValueError, TypeError):
                        valor_m = None

                if station_id is not None:
                    try:
                        station_id = int(station_id)
                    except (ValueError, TypeError):
                        station_id = None

                if adjunto_id is not None:
                    try:
                        adjunto_id = int(adjunto_id)
                    except (ValueError, TypeError):
                        adjunto_id = None

                updated = self.store.update_measurement(
                    measurement_id=m_id,
                    station_id=station_id,
                    station_name=station_name,
                    valor_metros=valor_m,
                    tendencia_rio=tendencia,
                    timestamp_medicion=ts_med,
                    estado_revision=estado_rev,
                    adjunto_id=adjunto_id,
                    foto_path=foto_path,
                    fijar_operador=fijar_operador,
                )

                if updated:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "message": "Medición actualizada exitosamente",
                        "medicion": updated
                    }, ensure_ascii=False).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": f"Medición #{m_id} no encontrada"
                    }, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
                return

        self.send_error(404, "Ruta PUT no encontrada")

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = parsed.path
        match = re.match(r"^/api/mediciones/(\d+)$", path)
        if match:
            try:
                m_id = int(match.group(1))
                deleted = self.store.delete_measurement(m_id, soft=True)
                if deleted:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": True,
                        "message": "Medición descartada (soft delete)",
                        "id": m_id,
                        "estado_revision": "DESCARTADO"
                    }, ensure_ascii=False).encode("utf-8"))
                else:
                    self.send_response(404)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    self.wfile.write(json.dumps({
                        "success": False,
                        "error": f"Medición #{m_id} no encontrada"
                    }, ensure_ascii=False).encode("utf-8"))
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": str(e)}, ensure_ascii=False).encode("utf-8"))
                return

        self.send_error(404, "Ruta DELETE no encontrada")

    def log_message(self, format, *args):
        # Silenciar logs ruidosos de HTTP estándar
        pass


def run_dashboard(port: int = 5000, db_path: str = None, photos_dir: str = None):
    config = BotConfig.load()
    store = MeasurementStore(
        db_path=db_path or config.measurement_db_path,
        photos_dir=photos_dir or config.photos_dir,
    )
    DashboardHTTPHandler.store = store

    server_address = ("", port)
    httpd = HTTPServer(server_address, DashboardHTTPHandler)
    print(f"🚀 Dashboard de Hidrometría iniciado en http://localhost:{port}")
    print(f"📁 Base de datos: {store.db_path}")
    print(f"📷 Directorio de fotos: {store.photos_dir}")
    print("Presiona Ctrl+C para detener el servidor.\n")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor dashboard detenido.")
        httpd.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Servidor Web del Dashboard de Mediciones Limnimétricas")
    parser.add_argument("--puerto", "-p", type=int, default=5000, help="Puerto HTTP (default: 5000)")
    parser.add_argument("--db", default=None, help="Ruta de SQLite mediciones.db")
    args = parser.parse_args()

    run_dashboard(port=args.puerto, db_path=args.db)

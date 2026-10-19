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
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
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
    
    /* Leaflet & Map Catalog */
    #mapa-estaciones { height: 380px; border-radius: 8px; margin-bottom: 16px; border: 1px solid var(--border); }
    .station-card { background: #0f172a; border: 1px solid var(--border); border-radius: 6px; padding: 12px 14px; cursor: pointer; transition: all 0.2s; }
    .station-card:hover { border-color: var(--primary); background: #162032; }

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

    /* Modal */
    .modal { display: none; position: fixed; z-index: 100; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.85); align-items: center; justify-content: center; backdrop-filter: blur(4px); }
    .modal.active { display: flex; }
    .modal-content { background: var(--card-bg); border: 1px solid var(--border); border-radius: 10px; max-width: 850px; width: 92%; max-height: 92vh; overflow: hidden; display: flex; flex-direction: column; }
    .modal-header { padding: 14px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
    .modal-body { padding: 20px; overflow-y: auto; text-align: center; }
    .modal-img { max-width: 100%; max-height: 48vh; border-radius: 6px; object-fit: contain; border: 1px solid var(--border); }
    .close-btn { background: none; border: none; color: var(--text-muted); font-size: 1.5rem; cursor: pointer; }
    .close-btn:hover { color: var(--text); }
    .meta-box { background: #0f172a; padding: 14px; border-radius: 6px; margin-top: 14px; text-align: left; font-size: 0.88rem; line-height: 1.5; }

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
        <a href="/api/export" id="btn-export" class="btn btn-secondary" target="_blank">📥 Exportar CSV</a>
        <button onclick="cargarDatos()" class="btn">🔄 Actualizar</button>
      </div>
    </header>

    <!-- Mapa Interactivo y Catálogo de Estaciones -->
    <div class="panel" style="margin-bottom: 24px;">
      <div class="panel-title">
        <span>🗺️ Catálogo Geográfico y Mapa de Estaciones</span>
        <span id="mapa-sub" style="font-size: 0.85rem; color: var(--text-muted);">Haz clic en un marcador o estación para abrir su chat de WhatsApp</span>
      </div>
      <div id="mapa-estaciones" style="height: 380px; border-radius: 8px; margin-bottom: 16px; border: 1px solid var(--border);"></div>
      <div id="catalogo-estaciones-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; max-height: 220px; overflow-y: auto;"></div>
    </div>

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

  <!-- Modal Detallado: Visor de Fotos, Chat Cronológico y Corrección -->
  <div class="modal" id="modal-foto" onclick="cerrarModal(event)">
    <div class="modal-content" onclick="event.stopPropagation()">
      <div class="modal-header">
        <h3 id="modal-titulo">Detalle de Medición</h3>
        <button class="close-btn" onclick="cerrarModal()">&times;</button>
      </div>
      <div class="modal-body">
        <img id="modal-img" src="" alt="Regla Limnimétrica" class="modal-img">
        <div id="modal-edit-box"></div>
        <div id="modal-chat-stream"></div>
        <div class="meta-box" id="modal-meta"></div>
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

    let mapInstance = null;
    let markersLayer = null;

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
        inicializarMapa();
        renderMapaEstaciones(estacionesData);
        renderCatalogoEstaciones(estacionesData);
        renderTabla(medicionesData);
        actualizarGrafico();
      } catch (e) {
        console.error("Error al cargar datos:", e);
      }
    }

    function inicializarMapa() {
      if (typeof L === 'undefined') return;
      if (!mapInstance) {
        const mapEl = document.getElementById('mapa-estaciones');
        if (!mapEl) return;
        mapInstance = L.map('mapa-estaciones').setView([-25.5, -57.5], 6);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
          maxZoom: 19,
          attribution: '&copy; CartoDB &copy; OpenStreetMap'
        }).addTo(mapInstance);
        markersLayer = L.layerGroup().addTo(mapInstance);
      }
    }

    function renderMapaEstaciones(estaciones) {
      if (!mapInstance || !markersLayer) return;
      markersLayer.clearLayers();
      const bounds = [];

      estaciones.forEach(st => {
        if (st.latitud !== null && st.longitud !== null && st.latitud !== undefined && st.longitud !== undefined) {
          const lat = parseFloat(st.latitud);
          const lon = parseFloat(st.longitud);
          if (isNaN(lat) || isNaN(lon)) return;
          bounds.push([lat, lon]);

          let color = '#38bdf8';
          const tend = (st.ultima_tendencia || '').toUpperCase();
          if (tend.includes('CRECE')) color = '#22c55e';
          else if (tend.includes('BAJA')) color = '#ef4444';
          else if (tend.includes('ESTAC')) color = '#818cf8';

          const marker = L.circleMarker([lat, lon], {
            radius: 8,
            fillColor: color,
            color: '#ffffff',
            weight: 1.5,
            opacity: 0.9,
            fillOpacity: 0.85
          });

          const nivelStr = (st.ultimo_nivel_metros !== null && st.ultimo_nivel_metros !== undefined)
            ? `${parseFloat(st.ultimo_nivel_metros).toFixed(2)} m`
            : 'Sin lectura reciente';
          const targetId = st.id || st.nombre;

          const popupContent = `
            <div style="font-family:-apple-system,BlinkMacSystemFont,sans-serif; color:#0f172a; min-width:180px;">
              <h4 style="margin:0 0 4px 0; font-size:0.95rem; color:#0369a1;">⚓ ${st.nombre}</h4>
              <div style="font-size:0.8rem; color:#64748b; margin-bottom:6px;">${st.rio || 'Cuenca'}</div>
              <div style="font-size:0.82rem; margin-bottom:4px;"><b>Nivel:</b> ${nivelStr} <span style="font-size:0.75rem; font-weight:700;">${st.ultima_tendencia || ''}</span></div>
              <div style="font-size:0.75rem; color:#64748b; margin-bottom:8px;">Total reportes: ${st.total_mediciones || 0}</div>
              <button style="width:100%; background:#005c4b; color:#fff; border:none; padding:6px 10px; border-radius:4px; font-weight:600; cursor:pointer; font-size:0.8rem; display:flex; align-items:center; justify-content:center; gap:6px;" onclick="abrirChatEstacion('${targetId}')">💬 Ver Chat de WhatsApp</button>
            </div>
          `;
          marker.bindPopup(popupContent);
          markersLayer.addLayer(marker);
        }
      });

      if (bounds.length > 0) {
        try {
          mapInstance.fitBounds(bounds, { padding: [30, 30], maxZoom: 10 });
        } catch (e) {}
      }
    }

    function renderCatalogoEstaciones(estaciones) {
      const container = document.getElementById('catalogo-estaciones-grid');
      if (!container) return;
      container.innerHTML = estaciones.map(st => {
        const nivelStr = (st.ultimo_nivel_metros !== null && st.ultimo_nivel_metros !== undefined)
          ? `<b>${parseFloat(st.ultimo_nivel_metros).toFixed(2)} m</b>`
          : '<span style="color:var(--text-muted)">-</span>';
        const targetId = st.id || st.nombre;
        return `
          <div class="station-card" onclick="abrirChatEstacion('${targetId}')">
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:700; color:var(--text); font-size:0.95rem;">${st.nombre}</span>
              <span class="badge badge-origen" style="font-size:0.68rem;">💬 Chat</span>
            </div>
            <div style="font-size:0.78rem; color:var(--text-muted); margin:3px 0;">${st.rio || '-'}</div>
            <div style="display:flex; justify-content:space-between; align-items:center; font-size:0.82rem; margin-top:6px;">
              <span>${nivelStr} <span style="font-size:0.72rem; color:var(--text-muted);">${st.ultima_tendencia || ''}</span></span>
              <span style="font-size:0.72rem; color:var(--text-muted);">${st.total_mediciones || 0} meds</span>
            </div>
          </div>
        `;
      }).join('');
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
        .replace(/\n/g, '<br>');
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

      // Actualizar enlace de exportación con los mismos filtros
      const params = new URLSearchParams();
      if (estacion) params.append('estacion', estacion);
      if (desde) params.append('desde', desde);
      if (hasta) params.append('hasta', hasta);
      if (soloFotos) params.append('fotos', 'true');
      document.getElementById('btn-export').href = '/api/export?' + params.toString();

      const filtradas = medicionesData.filter(m => {
        if (estacion && (m.estacion_nombre_norm !== estacion && m.estacion_detectada !== estacion)) return false;
        if (desde && m.timestamp_medicion < desde) return false;
        if (hasta && m.timestamp_medicion > hasta + ' 23:59:59') return false;
        if (soloFotos && !m.foto_path) return false;
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

      // Filtrar sólo aquellos que tengan nivel en metros válido
      const validos = dataToChart.filter(m => m.valor_metros !== null);

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

    function abrirDetallePorId(id) {
      const m = medicionesData.find(x => x.id === id);
      if (m) {
        abrirDetalle(m);
      }
    }

    async function abrirDetalle(m) {
      const stName = m.estacion_nombre_norm || m.estacion_detectada || '';
      document.getElementById('modal-titulo').textContent = `Detalle de Medición #${m.id} - ${stName}`;

      const imgEl = document.getElementById('modal-img');
      if (m.foto_path) {
        imgEl.style.display = 'inline-block';
        imgEl.src = '/' + m.foto_path;
      } else {
        imgEl.style.display = 'none';
      }

      // 1. Tarjeta de Corrección Manual de Estación y Nivel
      const nivelVal = m.valor_metros !== null ? m.valor_metros : '';
      document.getElementById('modal-edit-box').innerHTML = `
        <div class="edit-card">
          <div class="edit-card-title">✏️ Corregir Estación y Medición</div>
          <div class="edit-grid">
            <div>
              <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Estación Hidrométrica:</label>
              <input type="text" id="input-edit-estacion" list="dl-estaciones-editar" class="filter-input" style="width:100%; box-sizing:border-box;" value="${stName}">
            </div>
            <div>
              <label style="font-size:0.75rem; color:var(--text-muted); display:block; margin-bottom:4px;">Nivel en metros (m):</label>
              <input type="number" step="0.01" id="input-edit-nivel" class="filter-input" style="width:100%; box-sizing:border-box;" value="${nivelVal}">
            </div>
            <div>
              <button class="btn" style="background:var(--primary); color:#000; font-weight:700; white-space:nowrap; padding:8px 14px; cursor:pointer;" onclick="guardarCorreccion(${m.id})">💾 Guardar</button>
            </div>
          </div>
          <div id="edit-feedback" style="margin-top:8px; font-size:0.85rem; font-weight:600;"></div>
        </div>
      `;

      // 2. Cargar mensajes en orden cronológico asociados a la sesión
      const streamEl = document.getElementById('modal-chat-stream');
      streamEl.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem; padding:8px 0;">Cargando mensajes del operador en orden cronológico...</div>';

      // 3. Metadatos adicionales de la medición
      let fotoBadge = m.foto_path 
        ? `<span style="font-family:monospace; color:var(--primary);">${m.foto_path}</span>`
        : `<span style="color:var(--text-muted); font-style:italic;">Sin fotografía adjunta (reporte de texto)</span>`;

      document.getElementById('modal-meta').innerHTML = `
        <div style="display:grid; grid-template-columns: 1fr 1fr; gap:8px 16px; margin-top:4px;">
          <div><b>Fecha y Hora:</b> ${m.timestamp_medicion}</div>
          <div><b>Estación:</b> ${stName} (${m.estacion_rio || 'Cuenca'})</div>
          <div><b>Nivel:</b> ${m.valor_metros !== null ? `<b>${m.valor_metros.toFixed(2)} m</b> (${m.valor_cm ? m.valor_cm.toFixed(1) : (m.valor_metros*100).toFixed(1)} cm)` : '<span style="color:var(--warning)">Pendiente de lectura</span>'}</div>
          <div><b>Tendencia:</b> ${m.tendencia_rio || 'No indicada'}</div>
          <div><b>Operador:</b> ${m.remitente_nombre || ''} (+${m.remitente_telefono})</div>
          <div><b>Origen del dato:</b> <span class="badge badge-origen">${m.origen_dato || 'texto'}</span></div>
        </div>
        <div style="margin-top:10px; font-size:0.85rem; border-top:1px solid #334155; padding-top:8px;">
          <b>Análisis de IA:</b> ${m.observaciones_ia || 'Sin observaciones adicionales'}<br>
          <b>Archivo de Imagen:</b> ${fotoBadge}
        </div>
      `;

      document.getElementById('modal-foto').classList.add('active');

      // Petición asíncrona de mensajes cronológicos
      try {
        const res = await fetch(`/api/mediciones/${m.id}/contexto`);
        const data = await res.json();
        const msgs = data.mensajes || [];
        if (msgs.length === 0) {
          streamEl.innerHTML = '<div style="color:var(--text-muted); font-size:0.85rem; font-style:italic; padding:6px 0;">No se encontraron mensajes adicionales en la ventana de esta sesión.</div>';
          return;
        }

        let html = `
          <div class="chat-stream">
            <div class="chat-stream-title">💬 Mensajes del Operador (${msgs.length} mensajes en orden cronológico)</div>
        `;
        msgs.forEach(msg => {
          const sender = msg.remitente_nombre || 'Operador';
          const text = msg.texto ? msg.texto.replace(/</g, '&lt;').replace(/>/g, '&gt;') : '<span style="color:var(--text-muted); font-style:italic;">(Mensaje sin texto)</span>';
          const att = msg.archivo_adjunto ? `<div class="chat-bubble-att">📸 Archivo adjunto: ${msg.archivo_adjunto}</div>` : '';
          html += `
            <div class="chat-bubble">
              <div class="chat-bubble-header">
                <span>👤 <b>${sender}</b></span>
                <span>🕒 ${msg.timestamp_mensaje}</span>
              </div>
              <div class="chat-bubble-text">${text}</div>
              ${att}
            </div>
          `;
        });
        html += '</div>';
        streamEl.innerHTML = html;
      } catch (e) {
        console.error("Error al obtener contexto cronológico:", e);
        streamEl.innerHTML = '<div style="color:var(--danger); font-size:0.85rem;">Error al cargar mensajes cronológicos.</div>';
      }
    }

    async function guardarCorreccion(mId) {
      const newEst = document.getElementById('input-edit-estacion').value.trim();
      const newNivelStr = document.getElementById('input-edit-nivel').value;
      const feedback = document.getElementById('edit-feedback');
      feedback.style.color = '#38bdf8';
      feedback.textContent = 'Guardando corrección...';

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
          feedback.style.color = 'var(--success)';
          feedback.textContent = '✅ ¡Medición y estación corregidas exitosamente!';

          // Actualizar registro en arreglo local
          const idx = medicionesData.findIndex(x => x.id === mId);
          if (idx !== -1) {
            medicionesData[idx] = data.medicion;
          }
          // Recargar estaciones si se ingresó un nombre nuevo
          fetch('/api/estaciones').then(r => r.json()).then(stData => {
            estacionesData = stData;
            actualizarEstacionesSelect();
          });

          // Re-renderizar tabla y gráfico
          aplicarFiltros();
        } else {
          feedback.style.color = 'var(--danger)';
          feedback.textContent = '❌ Error al guardar corrección.';
        }
      } catch (e) {
        feedback.style.color = 'var(--danger)';
        feedback.textContent = '❌ Error de red al guardar: ' + e;
      }
    }

    // Alias para compatibilidad
    const abrirFoto = abrirDetalle;

    function cerrarModal() {
      document.getElementById('modal-foto').classList.remove('active');
    }

    document.addEventListener('keydown', e => {
      if (e.key === 'Escape') {
        cerrarLightbox();
        cerrarChatModal();
        cerrarModal();
      }
    });

    window.onload = cargarDatos;
  </script>
</body>
</html>
"""


class DashboardHTTPHandler(BaseHTTPRequestHandler):
    store: MeasurementStore = None

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

            mediciones = self.store.query_measurements(
                estacion_nombre=estacion,
                fecha_desde=desde,
                fecha_hasta=hasta,
                solo_con_foto=solo_fotos,
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

        # 4. API Exportación CSV
        if path == "/api/export":
            estacion = query.get("estacion", [None])[0]
            desde = query.get("desde", [None])[0]
            hasta = query.get("hasta", [None])[0]
            solo_fotos = query.get("fotos", ["false"])[0].lower() in ("true", "1")

            temp_fd, temp_csv = tempfile.mkstemp(suffix=".csv")
            os.close(temp_fd)
            try:
                self.store.export_to_csv(
                    output_path=temp_csv,
                    estacion_nombre=estacion,
                    fecha_desde=desde,
                    fecha_hasta=hasta,
                    solo_con_foto=solo_fotos,
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

        # Corregir estación y medición: /api/mediciones/<id>/editar
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

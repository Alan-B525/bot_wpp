"""
scripts/migrate_database.py
Script de migración segura y con cero pérdida de datos para data/mediciones.db.

Normaliza el esquema de SQLite introduciendo:
- operadores
- operador_estaciones
- adjuntos_multimedia
- vinculación biunívoca de fotos a mensajes y mediciones
- coordenadas geográficas y catálogo enriquecido de estaciones
- saneamiento de estaciones espurias manteniendo total retrocompatibilidad.
"""

import os
import sys
import re
import json
import shutil
import sqlite3
import argparse
from datetime import datetime
from typing import Dict, Any, Tuple

# Asegurar importación de módulos del proyecto
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from bot.measurement_store import MeasurementStore, DEFAULT_SEED_STATIONS, SPURIOUS_STATION_NAMES


def migrate_database(db_path: str = "data/mediciones.db", backup_path: str = "data/mediciones.db.bak") -> Dict[str, Any]:
    """
    Ejecuta la migración de la base de datos con verificación de conteos antes y después.
    Garantiza cero pérdida de datos (402 mediciones, 534 chats, 272 fotos vinculadas).
    """
    db_abs = os.path.abspath(db_path)
    if not os.path.exists(db_abs):
        raise FileNotFoundError(f"No se encontró la base de datos a migrar en: {db_abs}")

    # 1. Asegurar copia de seguridad
    backup_abs = os.path.abspath(backup_path)
    if not os.path.exists(backup_abs):
        print(f"📦 Creando copia de seguridad en: {backup_abs}...")
        shutil.copy2(db_abs, backup_abs)
    else:
        print(f"ℹ️ Copia de seguridad existente encontrada en: {backup_abs}")

    # 2. Conexión y conteos previos a la migración
    conn = sqlite3.connect(db_abs)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM mediciones")
    initial_meds_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM mensajes_chat")
    initial_chats_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM mediciones WHERE foto_path IS NOT NULL AND foto_path != ''")
    initial_photos_count = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM estaciones")
    initial_stations_count = cur.fetchone()[0]

    print("\n" + "="*70)
    print("📊 CONTEOS PREVIOS A LA MIGRACIÓN")
    print("="*70)
    print(f"• Total estaciones registradas:     {initial_stations_count}")
    print(f"• Total mediciones históricas:      {initial_meds_count} (Esperado: 402)")
    print(f"• Total mensajes de chat:           {initial_chats_count} (Esperado: 534)")
    print(f"• Total fotos referenciadas:        {initial_photos_count} (Esperado: 272)")
    print("="*70 + "\n")

    # 3. Inicializar / actualizar esquema usando MeasurementStore.init_db()
    conn.close()
    store = MeasurementStore(db_path=db_abs)
    store.init_db()

    conn = sqlite3.connect(db_abs)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # 4. Cargar remitentes de config.json si está disponible
    config_numbers = []
    config_file = os.path.join(PROJECT_ROOT, "config.json")
    if os.path.exists(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                config_numbers = cfg.get("source_numbers", [])
        except Exception as e:
            print(f"⚠️ Error leyendo config.json: {e}")

    # 5. Poblar operadores a partir de config.json, mediciones y mensajes_chat
    for num in config_numbers:
        raw_num = str(num).strip()
        if raw_num:
            cur.execute("""
                INSERT INTO operadores (telefono, nombre)
                VALUES (?, ?)
                ON CONFLICT(telefono) DO NOTHING
            """, (raw_num, raw_num))

    for r in cur.execute("SELECT DISTINCT remitente_telefono, remitente_nombre FROM mediciones").fetchall():
        t = str(r["remitente_telefono"] or "").strip()
        n = (r["remitente_nombre"] or "").strip() or None
        if t:
            cur.execute("""
                INSERT INTO operadores (telefono, nombre)
                VALUES (?, ?)
                ON CONFLICT(telefono) DO UPDATE SET
                    nombre = COALESCE(operadores.nombre, excluded.nombre)
            """, (t, n))

    for r in cur.execute("SELECT DISTINCT remitente_telefono, remitente_nombre FROM mensajes_chat").fetchall():
        t = str(r["remitente_telefono"] or "").strip()
        n = (r["remitente_nombre"] or "").strip() or None
        if t:
            cur.execute("""
                INSERT INTO operadores (telefono, nombre)
                VALUES (?, ?)
                ON CONFLICT(telefono) DO UPDATE SET
                    nombre = COALESCE(operadores.nombre, excluded.nombre)
            """, (t, n))
    conn.commit()

    # 6. Vincular mensajes_chat y mediciones con operadores
    cur.execute("""
        UPDATE mensajes_chat
        SET operador_id = (
            SELECT id FROM operadores 
            WHERE operadores.telefono = mensajes_chat.remitente_telefono
            LIMIT 1
        )
        WHERE operador_id IS NULL
    """)

    cur.execute("""
        UPDATE mediciones
        SET operador_id = (
            SELECT id FROM operadores 
            WHERE operadores.telefono = mediciones.remitente_telefono
            LIMIT 1
        )
        WHERE operador_id IS NULL
    """)
    conn.commit()

    # 7. Vincular biunívocamente fotos en adjuntos_multimedia
    photos_rows = cur.execute("""
        SELECT id, remitente_telefono, timestamp_medicion, foto_path, mensaje_texto
        FROM mediciones 
        WHERE foto_path IS NOT NULL AND foto_path != ''
    """).fetchall()

    for m in photos_rows:
        fpath = m["foto_path"]
        tel = re.sub(r"[^\w+]", "", str(m["remitente_telefono"] or "").strip())
        ts = m["timestamp_medicion"]

        # Match exacto con archivo_adjunto
        c_row = cur.execute("""
            SELECT id, archivo_adjunto FROM mensajes_chat
            WHERE remitente_telefono = ? AND timestamp_mensaje = ? AND archivo_adjunto IS NOT NULL
            LIMIT 1
        """, (tel, ts)).fetchone()

        if not c_row:
            # Match exacto de timestamp
            c_row = cur.execute("""
                SELECT id, archivo_adjunto FROM mensajes_chat
                WHERE remitente_telefono = ? AND timestamp_mensaje = ?
                LIMIT 1
            """, (tel, ts)).fetchone()

        if not c_row:
            # Ventana temporal de +-15 minutos
            c_row = cur.execute("""
                SELECT id, archivo_adjunto FROM mensajes_chat
                WHERE remitente_telefono = ?
                  AND timestamp_mensaje >= datetime(?, '-15 minutes')
                  AND timestamp_mensaje <= datetime(?, '+15 minutes')
                ORDER BY abs(strftime('%s', timestamp_mensaje) - strftime('%s', ?)) ASC
                LIMIT 1
            """, (tel, ts, ts, ts)).fetchone()

        msg_id = c_row["id"] if c_row else None
        orig_name = (c_row["archivo_adjunto"] if c_row and c_row["archivo_adjunto"] else os.path.basename(fpath))

        tamano = None
        full_disk_path = os.path.join(PROJECT_ROOT, fpath.replace("/", os.sep))
        if os.path.exists(full_disk_path):
            try:
                tamano = os.path.getsize(full_disk_path)
            except Exception:
                pass

        cur.execute("""
            INSERT INTO adjuntos_multimedia (mensaje_id, tipo, ruta_archivo, nombre_original, tamano_bytes, timestamp_captura)
            VALUES (?, 'imagen', ?, ?, ?, ?)
            ON CONFLICT(ruta_archivo) DO UPDATE SET
                mensaje_id = COALESCE(excluded.mensaje_id, adjuntos_multimedia.mensaje_id),
                nombre_original = COALESCE(excluded.nombre_original, adjuntos_multimedia.nombre_original),
                tamano_bytes = COALESCE(excluded.tamano_bytes, adjuntos_multimedia.tamano_bytes)
        """, (msg_id, fpath, orig_name, tamano, ts))

        cur.execute("SELECT id FROM adjuntos_multimedia WHERE ruta_archivo = ?", (fpath,))
        adj_id = cur.fetchone()[0]

        cur.execute("""
            UPDATE mediciones
            SET adjunto_id = ?,
                mensaje_id = COALESCE(mensaje_id, ?)
            WHERE id = ?
        """, (adj_id, msg_id, m["id"]))

        if msg_id:
            cur.execute("""
                UPDATE mensajes_chat
                SET foto_path = ?
                WHERE id = ? AND (foto_path IS NULL OR foto_path = '')
            """, (fpath, msg_id))

    conn.commit()

    # 8. Para mediciones sin foto, vincular mensaje_id a mensajes_chat
    cur.execute("""
        UPDATE mediciones
        SET mensaje_id = (
            SELECT c.id FROM mensajes_chat c
            WHERE c.remitente_telefono = mediciones.remitente_telefono
              AND c.timestamp_mensaje = mediciones.timestamp_medicion
            LIMIT 1
        )
        WHERE mensaje_id IS NULL
    """)
    conn.commit()

    # 9. Saneamiento de estaciones espurias y reasignación de mediciones
    # Localizar estación canónica Coratei
    cur.execute("SELECT id FROM estaciones WHERE nombre = 'Coratei'")
    coratei_row = cur.fetchone()
    coratei_id = coratei_row[0] if coratei_row else 2080

    # Localizar estación canónica Ayolas
    cur.execute("SELECT id FROM estaciones WHERE nombre = 'Ayolas'")
    ayolas_row = cur.fetchone()
    ayolas_id = ayolas_row[0] if ayolas_row else 17

    # Localizar estación canónica Panchito López
    cur.execute("SELECT id FROM estaciones WHERE nombre = 'Panchito López'")
    panchito_row = cur.fetchone()
    panchito_id = panchito_row[0] if panchito_row else 19

    # Reasignar mediciones #375 y #376 que mencionan explícitamente "Puerto Coratei"
    cur.execute("""
        UPDATE mediciones
        SET estacion_id = ?,
            estacion_detectada = 'Coratei',
            metodo_asignacion = 'explicito'
        WHERE id IN (375, 376)
    """, (coratei_id,))

    # Obtener IDs de estaciones espurias
    spurious_placeholders = ",".join("?" for _ in SPURIOUS_STATION_NAMES)
    spurious_ids = [r[0] for r in cur.execute(f"SELECT id FROM estaciones WHERE nombre IN ({spurious_placeholders})", SPURIOUS_STATION_NAMES).fetchall()]

    # Marcar estaciones espurias como inactivas (es_activa = 0)
    cur.execute(f"UPDATE estaciones SET es_activa = 0 WHERE nombre IN ({spurious_placeholders})", SPURIOUS_STATION_NAMES)

    # Identificar operadores de estación única consistente (100% fidelidad)
    # Fabio Marin (595972695099), Oscar Sánchez (595973472683), Salomón Diarte (595981302739), etc. -> Ayolas
    ayolas_senders = [
        "595972695099", "595973472683", "595981302739", "595982977772", "595983954804"
    ]
    for s_tel in ayolas_senders:
        if spurious_ids:
            cur.execute(f"""
                UPDATE mediciones
                SET estacion_id = ?,
                    estacion_detectada = 'Ayolas',
                    metodo_asignacion = 'inferido_operador'
                WHERE remitente_telefono = ?
                  AND estacion_id IN ({','.join('?'*len(spurious_ids))})
            """, [ayolas_id, s_tel] + spurious_ids)

    # Panchito López consistente: 595984607925
    if spurious_ids:
        cur.execute(f"""
            UPDATE mediciones
            SET estacion_id = ?,
                estacion_detectada = 'Panchito López',
                metodo_asignacion = 'inferido_operador'
            WHERE remitente_telefono = '595984607925'
              AND estacion_id IN ({','.join('?'*len(spurious_ids))})
        """, [panchito_id] + spurious_ids)

    # Mediciones restantes con estación espuria pertenecientes a operadores no clasificados
    # Se marcan con metodo_asignacion = 'desconocido' manteniendo el registro intacto
    if spurious_ids:
        cur.execute(f"""
            UPDATE mediciones
            SET metodo_asignacion = 'desconocido'
            WHERE estacion_id IN ({','.join('?'*len(spurious_ids))})
        """, spurious_ids)

    conn.commit()

    # 10. Calcular matriz de consistencia operador_estaciones
    cur.execute("""
        INSERT OR REPLACE INTO operador_estaciones (operador_id, estacion_id, total_reportes, ultimo_reporte, es_consistente)
        SELECT 
            m.operador_id,
            m.estacion_id,
            COUNT(m.id) as total_reportes,
            MAX(m.timestamp_medicion) as ultimo_reporte,
            0 as es_consistente
        FROM mediciones m
        JOIN estaciones e ON m.estacion_id = e.id
        WHERE m.operador_id IS NOT NULL 
          AND e.es_activa = 1
        GROUP BY m.operador_id, m.estacion_id
    """)

    # Detectar operadores consistentes (>= 2 reportes y >= 80% de dominancia en una estación)
    distinct_ops = [r[0] for r in cur.execute("SELECT DISTINCT operador_id FROM operador_estaciones").fetchall()]
    consistent_ops_count = 0
    for op_id in distinct_ops:
        tot_row = cur.execute("SELECT SUM(total_reportes) FROM operador_estaciones WHERE operador_id = ?", (op_id,)).fetchone()
        tot = tot_row[0] if tot_row else 0
        if tot and tot >= 2:
            top = cur.execute("""
                SELECT estacion_id, total_reportes 
                FROM operador_estaciones 
                WHERE operador_id = ? 
                ORDER BY total_reportes DESC LIMIT 1
            """, (op_id,)).fetchone()
            if top and (top["total_reportes"] / tot) >= 0.80:
                cur.execute("""
                    UPDATE operador_estaciones 
                    SET es_consistente = 1 
                    WHERE operador_id = ? AND estacion_id = ?
                """, (op_id, top["estacion_id"]))
                cur.execute("""
                    UPDATE operadores 
                    SET estacion_fija_id = ? 
                    WHERE id = ?
                """, (top["estacion_id"], op_id))
                consistent_ops_count += 1

    conn.commit()

    # 11. Conteos y verificación post-migración
    final_meds_count = cur.execute("SELECT COUNT(*) FROM mediciones").fetchone()[0]
    final_chats_count = cur.execute("SELECT COUNT(*) FROM mensajes_chat").fetchone()[0]
    final_adjuntos_count = cur.execute("SELECT COUNT(*) FROM adjuntos_multimedia").fetchone()[0]
    meds_with_adj = cur.execute("SELECT COUNT(*) FROM mediciones WHERE adjunto_id IS NOT NULL").fetchone()[0]
    meds_with_msg = cur.execute("SELECT COUNT(*) FROM mediciones WHERE mensaje_id IS NOT NULL").fetchone()[0]
    meds_with_op = cur.execute("SELECT COUNT(*) FROM mediciones WHERE operador_id IS NOT NULL").fetchone()[0]
    operadores_count = cur.execute("SELECT COUNT(*) FROM operadores").fetchone()[0]
    active_stations_count = cur.execute("SELECT COUNT(*) FROM estaciones WHERE es_activa = 1").fetchone()[0]
    spurious_active_count = cur.execute(f"SELECT COUNT(*) FROM estaciones WHERE es_activa = 1 AND nombre IN ({spurious_placeholders})", SPURIOUS_STATION_NAMES).fetchone()[0]

    # Verificar que las consultas existentes funcionan
    summary = store.get_stations_summary()
    assert len(summary) > 0, "get_stations_summary() no devolvió estaciones"
    assert "latitud" in summary[0], "get_stations_summary() no incluye latitud"
    assert "longitud" in summary[0], "get_stations_summary() no incluye longitud"

    history_ayolas = store.get_station_chat_history("Ayolas")
    assert history_ayolas["estacion"] is not None, "get_station_chat_history('Ayolas') no devolvió estación"

    print("\n" + "="*70)
    print("✅ VERIFICACIÓN POST-MIGRACIÓN (CERO PÉRDIDA DE DATOS)")
    print("="*70)
    print(f"• Mediciones antes:    {initial_meds_count} -> después: {final_meds_count} (Delta: {final_meds_count - initial_meds_count})")
    print(f"• Mensajes chat antes: {initial_chats_count} -> después: {final_chats_count} (Delta: {final_chats_count - initial_chats_count})")
    print(f"• Adjuntos creados:    {final_adjuntos_count} (Esperado: 272)")
    print(f"• Meds con adjunto_id: {meds_with_adj} / {initial_photos_count} fotos")
    print(f"• Meds con mensaje_id: {meds_with_msg} / {final_meds_count}")
    print(f"• Meds con operador_id:{meds_with_op} / {final_meds_count}")
    print(f"• Operadores creados:  {operadores_count} (Consistentes detectados: {consistent_ops_count})")
    print(f"• Estaciones activas:  {active_stations_count} (Espurias activas: {spurious_active_count})")
    print("="*70 + "\n")

    # Verificación estricta de invariantes
    assert final_meds_count == initial_meds_count, f"Error: Mediciones cambiaron de {initial_meds_count} a {final_meds_count}"
    assert final_chats_count == initial_chats_count, f"Error: Chats cambiaron de {initial_chats_count} a {final_chats_count}"
    assert final_adjuntos_count == initial_photos_count, f"Error: Adjuntos creados {final_adjuntos_count} != fotos iniciales {initial_photos_count}"
    assert meds_with_adj == initial_photos_count, f"Error: Meds con adjunto {meds_with_adj} != fotos iniciales {initial_photos_count}"
    assert meds_with_op == final_meds_count, f"Error: Hay {final_meds_count - meds_with_op} mediciones sin operador"
    assert spurious_active_count == 0, f"Error: Quedaron {spurious_active_count} estaciones espurias activas"

    conn.close()

    return {
        "status": "success",
        "initial_meds": initial_meds_count,
        "final_meds": final_meds_count,
        "initial_chats": initial_chats_count,
        "final_chats": final_chats_count,
        "adjuntos_creados": final_adjuntos_count,
        "meds_with_adj": meds_with_adj,
        "meds_with_op": meds_with_op,
        "operadores": operadores_count,
        "consistent_ops": consistent_ops_count,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migración de Base de Datos Hidrométrica SQLite")
    parser.add_argument("--db", default="data/mediciones.db", help="Ruta de SQLite mediciones.db")
    parser.add_argument("--backup", default="data/mediciones.db.bak", help="Ruta de copia de seguridad")
    args = parser.parse_args()

    try:
        res = migrate_database(db_path=args.db, backup_path=args.backup)
        print(f"🎉 ¡Migración completada exitosamente sin pérdida de datos!")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Error durante la migración: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

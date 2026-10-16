# 🤖 WhatsApp Forwarder Bot (Reenvío a Grupo)

Bot de WhatsApp en Python de alto rendimiento basado en **Neonize** (protocolo directo de WhatsApp Web multi-device sin navegadores pesados ni Puppeteer) que reenvía automáticamente los mensajes que recibe un número específico (o todos los chats privados) directamente a un grupo de WhatsApp.

---

## ✨ Características

- 📩 **Reenvío completo de contenidos**:
  - Textos simples y enriquecidos (enlaces, menciones).
  - Imágenes con o sin pie de foto (caption).
  - Videos y animaciones GIF con o sin descripción.
  - Audios y Notas de voz (Push-To-Talk) compatibles mediante FFmpeg.
  - Documentos y archivos adjuntos (PDFs, Word, Excel, ZIPs) preservando el nombre de archivo y tipo MIME.
  - Stickers.
  - Tarjetas de contacto y ubicaciones con enlace a Google Maps.
- 🏷️ **Encabezado personalizable**: Identifica claramente quién envió el mensaje, su número de teléfono y la fecha/hora exacta.
- 🎯 **Filtro flexible**:
  - Puedes definir uno o varios números específicos para vigilar en `source_numbers`.
  - O activar `forward_all_direct_messages: true` para reenviar todos los mensajes privados que le lleguen a la cuenta.
  - Ignora automáticamente mensajes que provengan de otros grupos o estados para evitar spam o bucles.
- 🔍 **Resolución inteligente de grupos**: Puedes indicar el nombre exacto de tu grupo (ej: `"Alertas Ventas"`) o su identificador JID (ej: `"120363041234567890@g.us"`).
- 📲 **Fácil vinculación por QR**: Muestra el código QR en la consola y además genera automáticamente el archivo `qr.png` para abrirlo y escanearlo cómodamente.
- 💾 **Sesión persistente**: Los datos de autenticación se guardan de forma segura en `bot_session.sqlite3`. Solo necesitas escanear el QR la primera vez.

---

## 📁 Estructura del Proyecto

```text
bot_wpp/
├── config.json             # Archivo principal de configuración
├── config.example.json     # Plantilla de ejemplo de configuración
├── main.py                 # Punto de entrada para ejecutar el bot
├── list_groups.py          # Utilidad para listar todos los grupos y sus IDs
├── start_bot.bat           # Acceso directo para iniciar el bot (doble clic en Windows)
├── list_groups.bat         # Acceso directo para ver tus grupos (doble clic en Windows)
├── reset_session.bat       # Acceso directo para borrar la sesión y pedir nuevo QR
├── requirements.txt        # Dependencias de Python
├── bot/
│   ├── __init__.py         # Módulo y configuración de codificación UTF-8
│   ├── config.py           # Gestor y validador de configuración
│   ├── client.py           # Cliente WhatsApp y gestión del ciclo de vida
│   ├── forwarder.py        # Motor de reenvío de mensajes y multimedia
│   └── utils.py            # Funciones auxiliares (teléfonos, QR, grupos)
└── tests/
    └── test_forwarder.py   # Suite de pruebas unitarias
```

---

## 🚀 Inicio Rápido

### 1. Configurar el bot (`config.json`)

Abre el archivo `config.json` con tu editor de texto favorito:

```json
{
  "source_numbers": [
    "5491112345678"
  ],
  "forward_all_direct_messages": false,
  "target_group": "Nombre de tu Grupo",
  "forward_header": false,
  "session_name": "bot_session.sqlite3"
}
```

#### Parámetros:
- **`source_numbers`**: Lista de números de teléfono cuyos mensajes deseas reenviar (con código de país, sin espacios ni símbolos `+`, ej: `"5491112345678"`).
- **`forward_all_direct_messages`**: Si lo pones en `true`, reenviará **todos** los mensajes directos que reciba tu cuenta de WhatsApp, ignorando la lista de números.
- **`target_group`**: El nombre del grupo de WhatsApp (ej: `"Mis Avisos"`) o su JID (ej: `"120363041234567890@g.us"`).
- **`forward_header`**: Está en `false` para reenvío **exacto y limpio** sin ningún texto adicional. (Si alguna vez quisieras agregar datos del remitente, puedes cambiarlo a `true`).

---

### 2. ¿No sabes el nombre o ID exacto de tu grupo?

Puedes ejecutar el listador de grupos:
- Haciendo doble clic en `list_groups.bat`
- O desde la consola:
  ```powershell
  python list_groups.py
  ```

El script se conectará a tu cuenta, listará todos los grupos con sus nombres y JIDs, y te mostrará el texto exacto que debes pegar en `target_group`.

---

### 3. Iniciar el Bot

- **En Windows:** Haz doble clic sobre `start_bot.bat`.
- **O por consola:**
  ```powershell
  python main.py
  ```

#### Vinculación inicial:
1. En la consola aparecerá un código QR (y también se guardará como `qr.png` en la carpeta del bot).
2. Abre WhatsApp en tu teléfono -> **Ajustes** / **Menú** -> **Dispositivos vinculados** -> **Vincular un dispositivo**.
3. Escanea el código QR.
4. ¡Listo! Verás el mensaje `🟢 ¡BOT CONECTADO CON ÉXITO A WHATSAPP!` y el bot comenzará a vigilar los mensajes entrantes.

---

## 🧪 Pruebas Unitarias

Para comprobar el correcto funcionamiento de todos los módulos y tipos de reenvío:

```powershell
python -m unittest discover tests
```

---

## 💡 Consejos y Preguntas Frecuentes

1. **¿Qué pasa si cierro la ventana?**
   El bot se detiene. Para mantenerlo activo 24/7, déjalo corriendo en una ventana de consola o configúralo como servicio o tarea programada.
2. **¿Tengo que escanear el QR cada vez que lo inicio?**
   No. La sesión queda guardada en `bot_session.sqlite3`. Solo necesitas escanearlo la primera vez o si cierras la sesión explícitamente desde WhatsApp.
3. **¿Cómo cambio de cuenta?**
   Simplemente borra el archivo `bot_session.sqlite3` y al iniciar nuevamente te pedirá un nuevo código QR.
4. **¿Soporta números internacionales?**
   Sí, el comparador de números limpia y normaliza automáticamente códigos de país, prefijos y formatos telefónicos.

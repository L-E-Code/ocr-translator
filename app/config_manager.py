import os
import json
import copy
import tempfile
from logger_config import get_logger

logger = get_logger("Config")

# O arquivo fica na raiz do projeto, independente da pasta de onde o app foi aberto
CONFIG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.json")

# Versão do formato do arquivo; aumente ao renomear/remover chaves e acrescente a migração em _MIGRATIONS
CONFIG_VERSION = 1

DEFAULT_CONFIG = {
    "config_version": CONFIG_VERSION,
    "monitor_index": 0,
    "roi_mode": "bottom_third",  # 'custom', 'bottom_third', 'bottom_half', 'full'
    "last_custom_roi": None,
    "display_mode": "sidebar",  # 'sidebar' ou 'overlay'
    "source_lang": "ja",
    "target_lang": "en",
    "minimize_on_start": True,
    "debounce_ms": 200,  # espera para o texto assentar (50 = ultra rápido, 400 = conservador)
    "compute_device": "auto",  # 'auto' (GPU se disponível), 'gpu' ou 'cpu'
    "overlay_mode": "inplace",  # 'inplace' (cobre o texto original) ou 'subtitle' (legenda inferior)
    "overlay_opacity": 1.0,  # 0.3 a 1.0
    "groq_models": None  # ex: ["llama-3.1-8b-instant"] para menor latência; None usa o padrão
}

LANGUAGES = {"ja", "en", "pt", "es"}


# ----------------------------------------------------------------------
# Validação
# ----------------------------------------------------------------------
def _choice(options):
    def check(v):
        try:
            return v if v in options else _INVALID
        except TypeError:  # valor não hasheável (lista/dict)
            return _INVALID
    return check

def _int_range(low, high):
    def check(v):
        if isinstance(v, bool):
            return _INVALID
        try:
            n = int(v)
        except (TypeError, ValueError):
            return _INVALID
        return min(high, max(low, n))
    return check

def _float_range(low, high):
    def check(v):
        if isinstance(v, bool):
            return _INVALID
        try:
            n = float(v)
        except (TypeError, ValueError):
            return _INVALID
        if n != n:  # NaN
            return _INVALID
        return min(high, max(low, n))
    return check

def _boolean(v):
    return v if isinstance(v, bool) else _INVALID

def _roi(v):
    """Área personalizada: None ou dicionário com inteiros left/top/width/height positivos."""
    if v is None:
        return None
    if not isinstance(v, dict):
        return _INVALID
    out = {}
    for key in ("left", "top", "width", "height"):
        val = v.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return _INVALID
        out[key] = int(val)
    if out["width"] <= 0 or out["height"] <= 0:
        return _INVALID
    for key, fallback in (("offset_x", "left"), ("offset_y", "top")):
        val = v.get(key, out[fallback])
        out[key] = int(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else out[fallback]
    return out

def _model_list(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = [v]
    if isinstance(v, list):
        models = [m.strip() for m in v if isinstance(m, str) and m.strip()]
        return models or None
    return _INVALID

_INVALID = object()

_VALIDATORS = {
    "config_version": _int_range(0, 10_000),
    "monitor_index": _int_range(0, 64),
    "roi_mode": _choice({"custom", "bottom_third", "bottom_half", "full"}),
    "last_custom_roi": _roi,
    "display_mode": _choice({"sidebar", "overlay"}),
    "source_lang": _choice(LANGUAGES),
    "target_lang": _choice(LANGUAGES),
    "minimize_on_start": _boolean,
    "debounce_ms": _int_range(50, 400),
    "compute_device": _choice({"auto", "gpu", "cpu"}),
    "overlay_mode": _choice({"inplace", "subtitle"}),
    "overlay_opacity": _float_range(0.3, 1.0),
    "groq_models": _model_list,
}


def validate_config(config):
    """
    Devolve (config_corrigido, chaves_corrigidas). Valores inválidos voltam ao padrão;
    números fora do intervalo são limitados; chaves desconhecidas são preservadas.
    """
    fixed = []
    result = {}
    for key, value in config.items():
        check = _VALIDATORS.get(key)
        if check is None:
            result[key] = value
            continue
        cleaned = check(value)
        if cleaned is _INVALID:
            result[key] = copy.deepcopy(DEFAULT_CONFIG[key])
            fixed.append(key)
        else:
            if cleaned != value:
                fixed.append(key)
            result[key] = cleaned
    for key, default in DEFAULT_CONFIG.items():
        result.setdefault(key, copy.deepcopy(default))
    return result, fixed


# ----------------------------------------------------------------------
# Migração de versões antigas do arquivo
# ----------------------------------------------------------------------
def _migrate_0_to_1(data):
    # Arquivos criados antes do versionamento: o formato é o mesmo, só falta carimbar a versão
    return data

_MIGRATIONS = {0: _migrate_0_to_1}  # versão de origem -> função que leva à versão seguinte

def _migrate(data):
    version = data.get("config_version", 0)
    if not isinstance(version, int) or isinstance(version, bool):
        version = 0
    while version < CONFIG_VERSION:
        step = _MIGRATIONS.get(version)
        if step:
            data = step(dict(data))
        version += 1
        logger.info(f"Configuração migrada para a versão {version}.")
    data["config_version"] = CONFIG_VERSION
    return data


# ----------------------------------------------------------------------
# Leitura e gravação
# ----------------------------------------------------------------------
def _backup_corrupt_file():
    """Guarda uma cópia do arquivo ilegível para o usuário poder recuperar algo dele."""
    try:
        os.replace(CONFIG_FILE, CONFIG_FILE + ".corrupt")
        logger.warning(f"Arquivo ilegível preservado em {CONFIG_FILE}.corrupt")
    except OSError:
        pass

def _write_atomic(data):
    """Grava num arquivo temporário e troca de uma vez, para uma queda no meio não corromper o config."""
    folder = os.path.dirname(CONFIG_FILE)
    fd, tmp_path = tempfile.mkstemp(dir=folder, prefix=".config_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, CONFIG_FILE)
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise

def load_config():
    """Carrega as configurações salvas (migradas e validadas) ou retorna os padrões."""
    data = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                data = _migrate(loaded)
            else:
                raise ValueError("o conteúdo não é um objeto JSON")
        except Exception as e:
            logger.error(f"Erro ao ler {CONFIG_FILE}: {e}")
            _backup_corrupt_file()
            data = {}
    config, fixed = validate_config(data)
    if fixed:
        logger.warning(f"Valores inválidos corrigidos na configuração: {', '.join(fixed)}")
    return config

def save_config(config_dict):
    """Mescla as alterações às configurações salvas, valida e grava de forma atômica."""
    try:
        current = load_config()
        current.update(config_dict)
        current["config_version"] = CONFIG_VERSION
        current, _ = validate_config(current)
        _write_atomic(current)
        return True
    except Exception as e:
        logger.error(f"Erro ao salvar {CONFIG_FILE}: {e}")
        return False

def reset_config():
    """Restaura todas as preferências para os valores padrão e devolve a configuração resultante."""
    defaults = copy.deepcopy(DEFAULT_CONFIG)
    try:
        _write_atomic(defaults)
    except Exception as e:
        logger.error(f"Erro ao restaurar {CONFIG_FILE}: {e}")
    return defaults

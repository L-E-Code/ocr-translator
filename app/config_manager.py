import os
import json

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "monitor_index": 0,
    "roi_mode": "bottom_third",  # 'custom', 'bottom_third', 'bottom_half', 'full'
    "last_custom_roi": None,
    "display_mode": "sidebar",  # 'sidebar' ou 'overlay'
    "source_lang": "ja",
    "target_lang": "en",
    "minimize_on_start": True
}

def load_config():
    """Carrega as configurações salvas ou retorna os padrões."""
    config = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    config.update(data)
        except Exception as e:
            print(f"[Config] Erro ao ler {CONFIG_FILE}: {e}")
    return config

def save_config(config_dict):
    """Salva o dicionário de configurações no config.json."""
    try:
        current = load_config()
        current.update(config_dict)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[Config] Erro ao salvar {CONFIG_FILE}: {e}")
        return False


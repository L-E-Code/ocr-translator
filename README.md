# 🌍 Real-Time Translator Using OCR

> 🚧 **Work in progress**  
> This project is still under active development. New features, performance improvements and visual tweaks are constantly being implemented.

## 💻 Technologies Used

- **Language:** Python 3.10+
- **OCR and Computer Vision:** EasyOCR, OpenCV, NumPy
- **Screen Capture:** MSS
- **Graphical Interface (GUI):** PyQt6
- **Translation Engine:** Groq API (Qwen-2.5 27B), Deep-Translator (Google / MyMemory)
- **Environment Management:** Python-Dotenv, keyring (Windows Credential Manager)

## 🚀 How to Install and Run

### Prerequisites
* Python 3.10 or newer installed (make sure to check the **"Add Python to PATH"** option during installation).
* Internet connection to download the dependencies and models on the first run.

### Installation and Running
1. Double-click `start.bat`.
   * *If the `.venv` virtual environment does not exist yet, the script automatically calls `install.bat` to create the environment and install all the dependencies.*
2. If you prefer to install separately before running, just run `install.bat`.

### AI translation key (Groq)
The best translations use a free [Groq](https://console.groq.com/keys) key. Paste it in the app (**AI key (Groq) → Set key…**): it is stored in the Windows Credential Manager, not in a text file. A `GROQ_API_KEY` in the `.env` file still works as a fallback. Without any key, the app uses the free Google / MyMemory translators.

### Portable version (no Python needed)
`build_exe.bat` builds a folder with `OCR Translator.exe` that can be zipped and shared (`build_exe.bat cpu` builds the smaller CPU-only variant). Settings, glossaries, cache and logs are kept next to the `.exe`.

### Updates
On startup the app reads the latest release number from GitHub and shows a link when a newer one exists. Nothing is downloaded or installed automatically; you can turn the check off in the main window.

More details are in the [User Guide](docs/USER_GUIDE.md).

---

📌 *More details, usage examples and performance improvements will be added soon.*

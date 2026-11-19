# AnyClass 🧭

**Zero-token local decision engine for classifying Telegram Saved Messages, notes, photos, and links directly on consumer CPU/RAM with Ollama System One multimodal decision models (`d1-omni:600m` + `tev1:0.8b`).**

Includes:
1. **Live Telegram Bot Listener (`telegram_bot.py`)**: Replaces manual export imports. Forward or send any text, URL, photo, or document to your Telegram bot. It pre-processes the input (yt-dlp metadata/transcripts, image downscaling, domain extraction) and classifies it in real time with 0 generated tokens.
2. **User-Friendly YAML Configuration (`config.yaml`)**: Edit classes, descriptions, and Second Brain destinations directly in clean YAML.
3. **Interactive Local Dashboard (`index.html`)**: Real-time topic filtering, automatic GitHub starring commands, `yt-dlp` batch downloading scripts, and Notion Second Brain routing.

---

## ⚡ Why Decision Models (Zero Generated Tokens)?

Traditional generative LLMs generate free-form text token-by-token, which is computationally expensive, prone to hallucinations, slow on local CPU, and consumes gigabytes of VRAM.

**AnyClass uses Multimodal Decision Models via Ollama (`/v1/systemone`):**
- **0 Generated Tokens**: Reads single-token choice logits in a single forward pass.
- **Fast & Lightweight**: ~1s per message on an AMD Ryzen 5 CPU, taking only ~1.3 GB to ~2.9 GB of RAM.
- **Multimodal**: Classifies both text and images natively (`d1-omni:600m`).
- **Memory-Guarded**: Protects the machine against OOM with real-time `/proc/meminfo` and cgroup v2 pressure checks.
- **Enriched Pre-processing**: Uses `yt-dlp` to extract titles, channel, duration, and captions before inference.

---

## 🚀 Quick Start

### 1. Requirements
- Linux or macOS with [Ollama](https://ollama.com/) 0.35+
- Python 3.10+ (`PyYAML`, `Pillow`, `yt-dlp`)

Pull the recommended decision models:
```bash
ollama pull tev1:0.8b        # Fast text decision model (833 MB)
ollama pull d1-omni:600m     # Multimodal image & text decision model (849 MB)
```

### 2. Live Telegram Bot (Continuous Mode)
To replace manual export imports, run the live Telegram bot listener:
1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
2. Set your token in `config.yaml` or via environment variable:
   ```bash
   export TELEGRAM_BOT_TOKEN="123456789:ABCDEF..."
   ```
3. Start the bot:
   ```bash
   python3 telegram_bot.py
   ```
Whenever you send or forward a message, link, photo, or audio to the bot, it will pre-process it, run the decision model, reply with the classification, and append the record to `results.jsonl`.

You can also test the pipeline locally from CLI without Telegram:
```bash
# Test URL with yt-dlp metadata extraction
python3 telegram_bot.py --test-url "https://youtu.be/PxpFzHGasGI"

# Test text note
python3 telegram_bot.py --test-text "tassi di interesse e bond vigilantes"

# Test image classification
python3 telegram_bot.py --test-image "path/to/image.jpg"
```

### 3. Batch Mode (ChatExport result.json)
If you already have a Telegram desktop export:
```bash
python3 tg_classify.py ChatExport_YYYY-MM-DD/result.json --out results.jsonl
```

### 4. Open Interactive Dashboard
```bash
python3 -m http.server 8085
# Open in your browser: http://localhost:8085
```

---

## ⚙️ Customizing Classes (`config.yaml`)

Edit `config.yaml` to define your own taxonomy:
```yaml
classes:
  ai_tech_generico:
    name: "AI & Tech KB"
    description: "Articoli, video, paper, prompt engineering o tool di Intelligenza Artificiale"
    destination: "Notion: Tech & AI Knowledge Base"
    action: "Salva in Notion Database 'Tech & AI Knowledge Base'"

  trading_wiki:
    name: "Trading Wiki"
    description: "Trading algoritmico, bot di trading, credenziali MT5, indicatori quantitativi"
    destination: "GitHub Wiki: trading-agent-wiki"
    action: "Aggiungi a GitHub trading-agent-wiki"

  ricette_meal_prep:
    name: "Ricette & Meal Prep"
    description: "Ricette, cibo, meal prep, cucina, idee di alimentazione o video culinari"
    destination: "Notion: Meal Planner & Ricette"
    action: "Salva in Notion Database 'Meal Planner'"
```

---

## 🛡️ License

MIT License. Built for local-first, privacy-respecting knowledge management.

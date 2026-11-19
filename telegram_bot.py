#!/usr/bin/env python3
"""AnyClass Telegram Bot - Real-time zero-token multimodal classification listener.

Replaces manual export imports: send or forward any link, text, photo, audio or document
to your Telegram Bot. The message is preprocessed (yt-dlp metadata/transcripts, image resize,
domain extraction) and categorized in real time by local Ollama decision models (d1-omni:600m / tev1:0.8b).

Usage:
  python3 telegram_bot.py              # Start polling
  python3 telegram_bot.py --test-url "https://youtu.be/PxpFzHGasGI"
  python3 telegram_bot.py --test-text "ricordati di pagare la bolletta"
  python3 telegram_bot.py --test-image "photos/photo_1@16-09-2023_11-12-35.jpg"
"""
import argparse, base64, io, json, os, re, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path
from urllib.parse import urlparse
import yaml

HERE = Path(__file__).parent.resolve()
CONFIG_FILE = HERE / "config.yaml"
URL_RE = re.compile(r"https?://[^\s<>\")\]]+")


# ---------------------------------------------------------------- Configuration
def load_config():
    if not CONFIG_FILE.exists():
        sys.exit(f"File di configurazione non trovato: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        raw = f.read()

    # Expand environment variables like ${TELEGRAM_BOT_TOKEN}
    expanded = re.sub(r"\$\{([A-Z0-9_]+)\}", lambda m: os.environ.get(m.group(1), ""), raw)
    cfg = yaml.safe_load(expanded)

    # Fallback to direct env var if not set in yaml
    if not cfg.get("telegram", {}).get("bot_token"):
        cfg.setdefault("telegram", {})["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    return cfg


# ---------------------------------------------------------------- Pre-processing & Tools
def extract_media_metadata(url, ytdlp_path="yt-dlp"):
    """Extract metadata and transcription snippets from YouTube, Reels, TikTok via yt-dlp."""
    try:
        cmd = [
            ytdlp_path,
            "--dump-json",
            "--skip-download",
            "--no-warnings",
            "--no-playlist",
            url
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=25)
        if res.returncode == 0 and res.stdout.strip():
            d = json.loads(res.stdout)
            title = d.get("title") or ""
            desc = (d.get("description") or "").strip()
            if len(desc) > 300:
                desc = desc[:300] + "..."
            channel = d.get("uploader") or d.get("channel") or ""
            duration = d.get("duration")

            # Check for subtitle / auto-captions summary if available
            subs_summary = ""
            sub_entries = d.get("subtitles") or d.get("automatic_captions") or {}
            if sub_entries:
                subs_summary = f"[sottotitoli disponibili: {', '.join(list(sub_entries.keys())[:3])}]"

            parts = [f"Titolo multimediale: {title}"]
            if channel:
                parts.append(f"Canale/Autore: {channel}")
            if duration:
                parts.append(f"Durata: {duration}s")
            if desc:
                parts.append(f"Descrizione: {desc}")
            if subs_summary:
                parts.append(subs_summary)

            return {
                "title": title,
                "author": channel,
                "duration": duration,
                "text_summary": "\n".join(parts),
            }
    except Exception as e:
        return {"error": str(e), "text_summary": f"[yt-dlp error: {e}]"}

    return None


def resize_image_base64(image_bytes_or_path, max_side=512):
    """Resize image to max_side px and return base64 JPEG."""
    try:
        from PIL import Image
        if isinstance(image_bytes_or_path, (str, Path)):
            im = Image.open(image_bytes_or_path).convert("RGB")
        else:
            im = Image.open(io.BytesIO(image_bytes_or_path)).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception as e:
        print(f"Errore ridimensionamento immagine: {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------- Decision Engine
def run_decision(state_text, image_b64=None, cfg=None):
    """Zero-token multimodal decision inference via Ollama /v1/systemone."""
    if cfg is None:
        cfg = load_config()

    endpoint = cfg["model"].get("endpoint", "http://localhost:11434/v1/systemone")
    classes = cfg["classes"]

    # Choose model: multimodal if image is present, else text_only
    if image_b64:
        active_model = cfg["model"].get("multimodal", "d1-omni:600m")
    else:
        active_model = cfg["model"].get("text_only", "tev1:0.8b")

    criteria = {k: v["description"] for k, v in classes.items()}

    body = {
        "model": active_model,
        "state": state_text,
        "keep_alive": "15m",
        "questions": {
            "categoria": {
                "type": "choice",
                "instructions": "In quale categoria tematica precisa rientra questo contenuto?",
                "criteria": criteria
            },
            "azione_urgente": {
                "type": "noul",
                "instructions": "Il contenuto richiede un'azione urgente o una verifica immediata?"
            }
        }
    }
    if image_b64:
        body["images"] = [image_b64]

    req = urllib.request.Request(
        endpoint,
        json.dumps(body).encode(),
        {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)

    ans = data["answers"]
    c = ans["categoria"]
    cat_key = c["choice"]
    conf = c.get("confidence") or max(c.get("probabilities", {cat_key: 0.8}).values())
    urgent = ans.get("azione_urgente", {}).get("noul", 0.0)

    class_meta = classes.get(cat_key, {
        "name": cat_key,
        "destination": "Notion: Inbox",
        "action": "Smista manualmente"
    })

    return {
        "categoria": cat_key,
        "nome_classe": class_meta.get("name", cat_key),
        "destinazione": class_meta.get("destination", "Notion"),
        "proposta": class_meta.get("action", ""),
        "confidence": round(float(conf), 3),
        "azione_urgente_p": round(float(urgent), 2),
        "modello": active_model,
    }


# ---------------------------------------------------------------- Telegram Client
class TelegramBot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.token = cfg["telegram"]["bot_token"]
        if not self.token or self.token.startswith("${"):
            sys.exit("ERRORE: Inserisci il token Telegram in config.yaml o imposta TELEGRAM_BOT_TOKEN")
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.file_url = f"https://api.telegram.org/file/bot{self.token}"
        self.allowed_chat_id = cfg["telegram"].get("allowed_chat_id")
        self.inbox_dir = HERE / cfg["preprocessing"].get("inbox_dir", "./inbox")
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.results_file = HERE / cfg["preprocessing"].get("results_file", "./results.jsonl")

    def call_api(self, method, data=None):
        url = f"{self.api_url}/{method}"
        if data:
            req = urllib.request.Request(url, json.dumps(data).encode(), {"Content-Type": "application/json"})
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.load(resp)

    def send_message(self, chat_id, text, reply_to_message_id=None):
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        return self.call_api("sendMessage", data)

    def download_file(self, file_id, dest_filename):
        res = self.call_api("getFile", {"file_id": file_id})
        file_path = res["result"]["file_path"]
        download_url = f"{self.file_url}/{file_path}"
        dest_path = self.inbox_dir / dest_filename
        with urllib.request.urlopen(download_url) as resp:
            dest_path.write_bytes(resp.read())
        return dest_path

    def process_message(self, msg):
        chat_id = msg["chat"]["id"]
        if self.allowed_chat_id and str(chat_id) != str(self.allowed_chat_id):
            print(f"Messaggio ignorato da chat non autorizzata: {chat_id}")
            return

        msg_id = msg["message_id"]
        date_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(msg.get("date", time.time())))
        raw_text = msg.get("text") or msg.get("caption") or ""
        urls = URL_RE.findall(raw_text)
        domains = sorted({urlparse(u).netloc.removeprefix("www.") for u in urls})

        image_b64 = None
        file_saved = None
        photo_rel = None

        # 1. Handle Photos
        if "photo" in msg:
            largest_photo = msg["photo"][-1]
            ext = "jpg"
            fn = f"photo_{msg_id}_{int(time.time())}.{ext}"
            saved_path = self.download_file(largest_photo["file_id"], fn)
            file_saved = str(saved_path)
            photo_rel = f"inbox/{fn}"
            image_b64 = resize_image_base64(saved_path, self.cfg["preprocessing"].get("image_max_side_px", 512))

        # 2. Handle Documents
        elif "document" in msg:
            doc = msg["document"]
            orig_name = doc.get("file_name", f"doc_{msg_id}")
            saved_path = self.download_file(doc["file_id"], orig_name)
            file_saved = str(saved_path)

        # 3. Handle Voice / Audio
        elif "voice" in msg or "audio" in msg:
            audio_obj = msg.get("voice") or msg.get("audio")
            fn = f"audio_{msg_id}.ogg" if "voice" in msg else audio_obj.get("file_name", f"audio_{msg_id}.mp3")
            saved_path = self.download_file(audio_obj["file_id"], fn)
            file_saved = str(saved_path)

        # 4. Preprocessing: yt-dlp metadata for video URLs
        ytdlp_meta = None
        if urls and self.cfg["preprocessing"].get("extract_video_metadata", True):
            for u in urls:
                if any(k in u for k in ["youtube.com", "youtu.be", "instagram.com", "tiktok.com", "soundcloud.com"]):
                    ytdlp_path = self.cfg["preprocessing"].get("ytdlp_path", "yt-dlp")
                    ytdlp_meta = extract_media_metadata(u, ytdlp_path)
                    break

        # Construct Evidence state text
        evidence_parts = []
        if raw_text:
            evidence_parts.append(raw_text)
        if ytdlp_meta and ytdlp_meta.get("text_summary"):
            evidence_parts.append(f"\n[Metadati multimediali estratti]:\n{ytdlp_meta['text_summary']}")
        if file_saved:
            evidence_parts.append(f"[File allegato: {Path(file_saved).name}]")
        if domains:
            evidence_parts.append(f"[Domini: {', '.join(domains)}]")
        if msg.get("forward_from"):
            fwd_user = msg["forward_from"].get("username") or msg["forward_from"].get("first_name") or ""
            evidence_parts.append(f"[Inoltrato da: {fwd_user}]")

        state_text = "\n".join(evidence_parts).strip() or "Immagine/allegato salvato senza testo."

        # 5. Run Decision Model
        t0 = time.time()
        dec = run_decision(state_text, image_b64, self.cfg)
        latency = round(time.time() - t0, 2)

        # Command synthesis
        cmd = ""
        if urls and ("instagram.com" in urls[0] or "tiktok.com" in urls[0] or "youtu" in urls[0]):
            if dec["categoria"] == "musica_thasup":
                cmd = f"yt-dlp -x --audio-format mp3 \"{urls[0]}\""
            else:
                cmd = f"yt-dlp \"{urls[0]}\""

        # 6. Save Record to results.jsonl
        rec = {
            "id": msg_id,
            "date": date_iso,
            "text": raw_text,
            "media": "photo" if "photo" in msg else ("document" if "document" in msg else None),
            "urls": urls,
            "domains": domains,
            "forwarded_from": msg.get("forward_sender_name") or (msg.get("forward_from") or {}).get("first_name"),
            "file_name": Path(file_saved).name if file_saved else None,
            "photo": photo_rel,
            "categoria": dec["categoria"],
            "destinazione": dec["destinazione"],
            "proposta": dec["proposta"],
            "comando": cmd,
            "confidence": dec["confidence"],
            "metodo": f"model:{dec['modello']}",
            "azione_urgente_p": dec["azione_urgente_p"],
            "ytdlp_title": ytdlp_meta.get("title") if ytdlp_meta else None
        }

        with open(self.results_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 7. Reply on Telegram
        reply_lines = [
            f"🎯 <b>Categoria:</b> {dec['nome_classe']} ({int(dec['confidence']*100)}%)",
            f"📌 <b>Destinazione:</b> {dec['destinazione']}",
            f"⚡ <b>Azione:</b> {dec['proposta']}"
        ]
        if ytdlp_meta and ytdlp_meta.get("title"):
            reply_lines.append(f"ℹ️ <b>Titolo:</b> {ytdlp_meta['title']}")
        if cmd:
            reply_lines.append(f"💻 <code>{cmd}</code>")
        reply_lines.append(f"⏱️ <i>{latency}s · {dec['modello']} (0 token)</i>")

        self.send_message(chat_id, "\n".join(reply_lines), reply_to_message_id=msg_id)
        print(f"[{msg_id}] {dec['nome_classe']} ({dec['confidence']}) in {latency}s -> {dec['destinazione']}")

    def start_polling(self):
        print(f"=== AnyClass Bot in ascolto (modello: {self.cfg['model']['multimodal']}) ===")
        print(f"Premi Ctrl+C per fermare il bot.\n")
        offset = 0
        while True:
            try:
                res = self.call_api("getUpdates", {"offset": offset, "timeout": 30})
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        self.process_message(update["message"])
            except KeyboardInterrupt:
                print("\nBot arrestato dall'utente.")
                break
            except Exception as e:
                print(f"Errore polling Telegram: {e}", file=sys.stderr)
                time.sleep(3)


# ---------------------------------------------------------------- CLI Test Mode
def run_cli_test(args, cfg):
    print("=== TEST DECISION MODEL MULTIMODALE ===")
    state_text = ""
    img_b64 = None

    if args.test_url:
        ytdlp_path = cfg["preprocessing"].get("ytdlp_path", "yt-dlp")
        meta = extract_media_metadata(args.test_url, ytdlp_path)
        print(f"URL: {args.test_url}")
        if meta:
            print(f"Metadati estratti yt-dlp:\n{meta['text_summary']}\n")
            state_text = f"{args.test_url}\n{meta['text_summary']}"
        else:
            state_text = args.test_url

    elif args.test_text:
        state_text = args.test_text

    elif args.test_image:
        p = Path(args.test_image)
        if not p.is_file():
            sys.exit(f"Immagine non trovata: {p}")
        img_b64 = resize_image_base64(p, cfg["preprocessing"].get("image_max_side_px", 512))
        state_text = "Immagine salvata su Telegram."
        print(f"Immagine caricata: {p} ({len(img_b64)} chars base64)")

    t0 = time.time()
    res = run_decision(state_text, img_b64, cfg)
    elapsed = round(time.time() - t0, 2)

    print(f"Risultato in {elapsed}s:")
    print(f"  • Categoria   : {res['nome_classe']} ({res['categoria']})")
    print(f"  • Confidenza  : {res['confidence'] * 100:.1f}%")
    print(f"  • Destinazione: {res['destinazione']}")
    print(f"  • Azione      : {res['proposta']}")
    print(f"  • Modello     : {res['modello']} (zero token generati)")


def main():
    parser = argparse.ArgumentParser(description="AnyClass Telegram Bot Listener")
    parser.add_argument("--test-url", help="Test pre-processing e classificazione su un URL")
    parser.add_argument("--test-text", help="Test classificazione su una stringa di testo")
    parser.add_argument("--test-image", help="Test classificazione multimodale su un file immagine")
    args = parser.parse_args()

    cfg = load_config()

    if args.test_url or args.test_text or args.test_image:
        run_cli_test(args, cfg)
    else:
        bot = TelegramBot(cfg)
        bot.start_polling()


if __name__ == "__main__":
    main()

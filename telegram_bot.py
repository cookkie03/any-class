#!/usr/bin/env python3
"""AnyClass Telegram Bot - Real-time zero-token multimodal classification listener with Interactive Approval.

Replaces manual export imports: send or forward any link, text, photo, audio or document
to your Telegram Bot. The message is preprocessed (yt-dlp metadata/transcripts, image resize,
domain extraction), categorized by local Ollama decision models (d1-omni:600m / tev1:0.8b),
and responds with an interactive [ ✅ Approva ed Esegui ] button to run the synthesized terminal command.

Usage:
  python3 telegram_bot.py              # Start polling
  python3 telegram_bot.py --test-url "https://youtu.be/PxpFzHGasGI"
  python3 telegram_bot.py --test-text "ricordati di pagare la bolletta"
  python3 telegram_bot.py --test-image "path/to/image.jpg"
"""
import argparse, base64, html, io, json, os, re, shlex, subprocess, sys, time, urllib.request, urllib.parse
from pathlib import Path
from urllib.parse import urlparse
import yaml

HERE = Path(__file__).parent.resolve()
CONFIG_FILE = HERE / "config.yaml"
URL_RE = re.compile(r"https?://[^\s<>\")\]]+")

# In-memory store for pending user approvals: action_id -> dict
PENDING_ACTIONS = {}


# ---------------------------------------------------------------- Configuration
def load_dotenv(env_path=HERE / ".env"):
    """Lightweight zero-dependency .env loader."""
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'\"")
        if k and k not in os.environ:
            os.environ[k] = v


def load_config():
    load_dotenv()
    if not CONFIG_FILE.exists():
        sys.exit(f"File di configurazione non trovato: {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        raw = f.read()

    expanded = re.sub(r"\$\{([A-Z0-9_]+)\}", lambda m: os.environ.get(m.group(1), ""), raw)
    cfg = yaml.safe_load(expanded)

    telegram_cfg = cfg.setdefault("telegram", {})
    if not telegram_cfg.get("bot_token"):
        telegram_cfg["bot_token"] = os.environ.get("TELEGRAM_BOT_TOKEN", "")

    if not telegram_cfg.get("allowed_user_id"):
        env_uid = os.environ.get("TELEGRAM_ALLOWED_USER_ID", "").strip()
        if env_uid:
            telegram_cfg["allowed_user_id"] = env_uid

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


def fetch_local_webpage(url, timeout=8, max_chars=1200):
    """100% local webpage fetch: extracts title, meta description and clean text body without external services."""
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            if "text" not in content_type and "html" not in content_type and "json" not in content_type:
                return None
            raw = resp.read(150000).decode("utf-8", errors="ignore")

            # Title
            t_match = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I | re.S)
            title = html.unescape(t_match.group(1).strip()) if t_match else ""
            title = re.sub(r"\s+", " ", title)

            # Meta description
            desc = ""
            for pat in [
                r'<meta\s+name=["\'](?:description|twitter:description)["\']\s+content=["\'](.*?)["\']',
                r'<meta\s+property=["\']og:description["\']\s+content=["\'](.*?)["\']'
            ]:
                m = re.search(pat, raw, re.I | re.S)
                if m:
                    desc = html.unescape(m.group(1).strip())
                    break

            # Clean body text
            clean = re.sub(r"<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", raw, flags=re.I | re.S)
            text_only = re.sub(r"<[^>]+>", " ", clean)
            text_only = html.unescape(text_only)
            lines = [l.strip() for l in text_only.splitlines() if l.strip()]
            snippet = " ".join(" ".join(lines).split())[:max_chars]

            parts = [f"Link sorgente: {url}"]
            if title:
                parts.append(f"Titolo pagina: {title}")
            if desc:
                parts.append(f"Descrizione: {desc}")
            if snippet and snippet != desc:
                parts.append(f"Estratto contenuto:\n{snippet[:600]}...")

            return {
                "title": title,
                "description": desc,
                "text_summary": "\n".join(parts),
                "url": url
            }
    except Exception as e:
        return {"error": str(e), "text_summary": f"Link sorgente: {url}\n[Nota: fetch fallito ({e}), analizzo solo URL]", "url": url}


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
        "action": "Smista manualmente",
        "command_template": None
    })

    return {
        "categoria": cat_key,
        "nome_classe": class_meta.get("name", cat_key),
        "destinazione": class_meta.get("destination", "Notion"),
        "proposta": class_meta.get("action", ""),
        "command_template": class_meta.get("command_template"),
        "confidence": round(float(conf), 3),
        "azione_urgente_p": round(float(urgent), 2),
        "modello": active_model,
    }


def synthesize_command(dec, urls, file_saved, text):
    """Safely interpolate command template with real runtime parameters."""
    tpl = dec.get("command_template")
    if not tpl:
        return ""

    params = {}
    if urls:
        params["url"] = urls[0]

    if file_saved:
        params["file_path"] = str(Path(file_saved).resolve())

    # Detect GitHub repo
    gh_match = re.search(r"github\.com/([a-zA-Z0-9_\.-]+)/([a-zA-Z0-9_\.-]+)", text)
    if gh_match:
        params["github_repo"] = f"{gh_match.group(1)}/{gh_match.group(2)}"

    try:
        # If template requires a parameter we don't have (e.g. url or file_path), skip command
        needed_keys = re.findall(r"\{([a-zA-Z0-9_]+)\}", tpl)
        for k in needed_keys:
            if k not in params:
                return ""
        return tpl.format(**params)
    except Exception:
        return ""


# ---------------------------------------------------------------- Telegram Client
class TelegramBot:
    def __init__(self, cfg):
        self.cfg = cfg
        self.token = cfg["telegram"]["bot_token"]
        if not self.token or self.token.startswith("${"):
            sys.exit("ERRORE: Inserisci il token Telegram in config.yaml o imposta TELEGRAM_BOT_TOKEN")
        self.api_url = f"https://api.telegram.org/bot{self.token}"
        self.file_url = f"https://api.telegram.org/file/bot{self.token}"
        self.allowed_user_id = cfg["telegram"].get("allowed_user_id")

        paths_cfg = cfg.get("paths", {})
        self.pending_dir = HERE / paths_cfg.get("pending_dir", "./sources/pending")
        self.processed_dir = HERE / paths_cfg.get("processed_dir", "./sources/processed")
        self.failed_dir = HERE / paths_cfg.get("failed_dir", "./sources/failed")
        self.results_file = HERE / paths_cfg.get("results_file", "./results.jsonl")

        self.pending_dir.mkdir(parents=True, exist_ok=True)
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        self.failed_dir.mkdir(parents=True, exist_ok=True)

    def call_api(self, method, data=None):
        url = f"{self.api_url}/{method}"
        if data:
            req = urllib.request.Request(url, json.dumps(data).encode(), {"Content-Type": "application/json"})
        else:
            req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=40) as resp:
            return json.load(resp)

    def is_authorized(self, user_id):
        if not self.allowed_user_id:
            return True
        return str(user_id) == str(self.allowed_user_id)

    def send_message(self, chat_id, text, reply_to_message_id=None, reply_markup=None):
        data = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_to_message_id:
            data["reply_to_message_id"] = reply_to_message_id
        if reply_markup:
            data["reply_markup"] = reply_markup
        return self.call_api("sendMessage", data)

    def answer_callback(self, callback_query_id, text=None):
        data = {"callback_query_id": callback_query_id}
        if text:
            data["text"] = text
        return self.call_api("answerCallbackQuery", data)

    def edit_message(self, chat_id, message_id, text, reply_markup=None):
        data = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup is not None:
            data["reply_markup"] = reply_markup
        return self.call_api("editMessageText", data)

    def download_file(self, file_id, dest_filename):
        res = self.call_api("getFile", {"file_id": file_id})
        file_path = res["result"]["file_path"]
        download_url = f"{self.file_url}/{file_path}"
        dest_path = self.pending_dir / dest_filename
        with urllib.request.urlopen(download_url) as resp:
            dest_path.write_bytes(resp.read())
        return dest_path

    def handle_callback_query(self, cb):
        cb_id = cb["id"]
        from_user = cb["from"]
        user_id = from_user["id"]
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]
        data = cb.get("data", "")

        if not self.is_authorized(user_id):
            self.answer_callback(cb_id, "⛔ Accesso negato: User ID non autorizzato.")
            return

        parts = data.split(":", 1)
        action_type = parts[0]
        act_id = parts[1] if len(parts) > 1 else ""

        if action_type == "ignore":
            self.answer_callback(cb_id, "Azione ignorata.")
            orig_text = cb["message"].get("text", "")
            self.edit_message(chat_id, msg_id, orig_text + "\n\n<i>[❌ Azione ignorata dall'utente]</i>", reply_markup={"inline_keyboard": []})
            return

        if action_type == "approve":
            act = PENDING_ACTIONS.get(act_id)
            if not act:
                self.answer_callback(cb_id, "⚠️ Azione scaduta o non trovata.")
                return

            cmd = act["cmd"]
            self.answer_callback(cb_id, "⚡ Esecuzione comando in corso...")

            # Run command securely on local host
            try:
                expanded_cmd = os.path.expanduser(cmd)
                p = subprocess.run(expanded_cmd, shell=True, capture_output=True, text=True, timeout=120)
                out = (p.stdout + "\n" + p.stderr).strip()
                if len(out) > 400:
                    out = out[:400] + "..."

                status_emoji = "✅" if p.returncode == 0 else "⚠️"
                result_text = (
                    f"{status_emoji} <b>COMANDO ESEGUITO:</b>\n"
                    f"<code>{cmd}</code>\n\n"
                    f"📋 <b>Output (code {p.returncode}):</b>\n"
                    f"<pre>{out or '(Nessun output a video)'}</pre>"
                )
                self.edit_message(chat_id, msg_id, result_text, reply_markup={"inline_keyboard": []})
            except Exception as e:
                err_text = f"❌ <b>ERRORE ESECUZIONE:</b>\n<code>{cmd}</code>\n\nErrore: {e}"
                self.edit_message(chat_id, msg_id, err_text, reply_markup={"inline_keyboard": []})

    def process_message(self, msg):
        chat_id = msg["chat"]["id"]
        from_user = msg.get("from", {})
        user_id = from_user.get("id")

        raw_text = (msg.get("text") or msg.get("caption") or "").strip()

        # Command /start or /myid to display User ID
        if raw_text in ["/start", "/myid", "/id"]:
            welcome = (
                f"👋 Ciao {from_user.get('first_name', '')}!\n\n"
                f"🔑 Il tuo <b>User ID Telegram</b> è: <code>{user_id}</code>\n\n"
                f"Per sicurezza e per abilitare l'approvazione dei comandi solo a te, imposta in <code>config.yaml</code>:\n"
                f"<pre>telegram:\n  allowed_user_id: {user_id}</pre>\n\n"
                f"Puoi inviarmi qualsiasi messaggio, link, foto o file e lo categorizzerò in tempo reale!"
            )
            self.send_message(chat_id, welcome, reply_to_message_id=msg["message_id"])
            return

        if not self.is_authorized(user_id):
            print(f"Messaggio bloccato da utente non autorizzato ID: {user_id}")
            self.send_message(chat_id, "⛔ Accesso negato: questo bot è privato.")
            return

        msg_id = msg["message_id"]
        date_iso = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(msg.get("date", time.time())))
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

        # 4. Preprocessing: yt-dlp metadata for video URLs OR local webpage fetch for other URLs
        media_meta = None
        is_video_url = False
        if urls:
            u = urls[0]
            is_video = any(k in u for k in ["youtube.com", "youtu.be", "instagram.com", "tiktok.com", "soundcloud.com"])
            if is_video and self.cfg["preprocessing"].get("extract_video_metadata", True):
                ytdlp_path = self.cfg["preprocessing"].get("ytdlp_path", "yt-dlp")
                media_meta = extract_media_metadata(u, ytdlp_path)
                is_video_url = True
            elif not is_video and self.cfg["preprocessing"].get("fetch_web_links", True):
                media_meta = fetch_local_webpage(u)

        evidence_parts = []
        if raw_text:
            evidence_parts.append(raw_text)
        if media_meta and media_meta.get("text_summary"):
            label = "Metadati video estratti (yt-dlp)" if is_video_url else "Contenuto pagina web (fetch locale 100%)"
            evidence_parts.append(f"\n[{label}]:\n{media_meta['text_summary']}")
        if file_saved:
            evidence_parts.append(f"[File allegato: {Path(file_saved).name}]")
        if domains:
            evidence_parts.append(f"[Domini: {', '.join(domains)}]")
        if urls:
            evidence_parts.append(f"[Link sorgente allegato: {', '.join(urls)}]")
        if msg.get("forward_from"):
            fwd_user = msg["forward_from"].get("username") or msg["forward_from"].get("first_name") or ""
            evidence_parts.append(f"[Inoltrato da: {fwd_user}]")

        state_text = "\n".join(evidence_parts).strip() or "Immagine/allegato salvato senza testo."

        # 5. Run Multimodal Decision Model (0 generated tokens)
        t0 = time.time()
        try:
            dec = run_decision(state_text, image_b64, self.cfg)
            if saved_path and saved_path.is_file():
                proc_path = self.processed_dir / saved_path.name
                saved_path.rename(proc_path)
                file_saved = str(proc_path)
                if photo_rel:
                    photo_rel = f"sources/processed/{saved_path.name}"
        except Exception as e:
            if saved_path and saved_path.is_file():
                fail_path = self.failed_dir / saved_path.name
                saved_path.rename(fail_path)
            raise e
        latency = round(time.time() - t0, 2)

        # 6. Synthesize Terminal Command
        cmd = synthesize_command(dec, urls, file_saved, raw_text)

        # 7. Save Record to results.jsonl
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
            "web_title": media_meta.get("title") if media_meta else None
        }

        with open(self.results_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # 8. Construct Telegram Response with Approval Keyboard
        reply_lines = [
            f"🎯 <b>Categoria:</b> {dec['nome_classe']} ({int(dec['confidence']*100)}%)",
            f"📌 <b>Destinazione:</b> {dec['destinazione']}",
            f"⚡ <b>Azione:</b> {dec['proposta']}"
        ]
        if media_meta and media_meta.get("title"):
            reply_lines.append(f"ℹ️ <b>Titolo:</b> {media_meta['title']}")
        if urls:
            reply_lines.append(f"🔗 <b>Link sorgente:</b> {urls[0]}")
        if cmd:
            reply_lines.append(f"💻 <b>Comando:</b>\n<code>{cmd}</code>")
        reply_lines.append(f"⏱️ <i>{latency}s · {dec['modello']} (0 token)</i>")

        # Interactive buttons
        inline_keyboard = []
        if cmd:
            action_id = f"act_{msg_id}_{int(time.time())}"
            PENDING_ACTIONS[action_id] = {
                "cmd": cmd,
                "categoria": dec["categoria"],
                "destinazione": dec["destinazione"]
            }
            # Short label for button
            btn_label = "✅ Esegui: " + (cmd.split()[0] if len(cmd.split()) > 0 else "Comando")
            if len(btn_label) > 30:
                btn_label = btn_label[:30] + "..."
            inline_keyboard.append([
                {"text": btn_label, "callback_data": f"approve:{action_id}"},
                {"text": "❌ Ignora", "callback_data": f"ignore:{action_id}"}
            ])

        reply_markup = {"inline_keyboard": inline_keyboard} if inline_keyboard else None

        self.send_message(chat_id, "\n".join(reply_lines), reply_to_message_id=msg_id, reply_markup=reply_markup)
        print(f"[{msg_id}] {dec['nome_classe']} ({dec['confidence']}) in {latency}s -> {dec['destinazione']} (cmd: {bool(cmd)})")

    def start_polling(self):
        print(f"=== AnyClass Bot in ascolto ===")
        print(f"Modello multimodale: {self.cfg['model']['multimodal']}")
        print(f"User ID autorizzato: {self.allowed_user_id or 'TUTTI (inviami /myid per configurarlo)'}")
        print(f"Premi Ctrl+C per fermare il bot.\n")
        offset = 0
        while True:
            try:
                res = self.call_api("getUpdates", {"offset": offset, "timeout": 30})
                for update in res.get("result", []):
                    offset = update["update_id"] + 1
                    if "callback_query" in update:
                        self.handle_callback_query(update["callback_query"])
                    elif "message" in update:
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
    urls = []
    file_saved = None

    if args.test_url:
        urls = [args.test_url]
        u = args.test_url
        is_video = any(k in u for k in ["youtube.com", "youtu.be", "instagram.com", "tiktok.com", "soundcloud.com"])
        if is_video and cfg["preprocessing"].get("extract_video_metadata", True):
            ytdlp_path = cfg["preprocessing"].get("ytdlp_path", "yt-dlp")
            meta = extract_media_metadata(u, ytdlp_path)
            print(f"URL Video: {u}")
            if meta:
                print(f"Metadati estratti yt-dlp:\n{meta['text_summary']}\n")
                state_text = f"{u}\n{meta['text_summary']}\n[Link sorgente allegato: {u}]"
            else:
                state_text = f"{u}\n[Link sorgente allegato: {u}]"
        else:
            meta = fetch_local_webpage(u)
            print(f"URL Web (fetch locale 100%): {u}")
            if meta and meta.get("text_summary"):
                print(f"Contenuto estratto:\n{meta['text_summary']}\n")
                state_text = f"{meta['text_summary']}\n[Link sorgente allegato: {u}]"
            else:
                state_text = f"{u}\n[Link sorgente allegato: {u}]"

    elif args.test_text:
        state_text = args.test_text
        urls = URL_RE.findall(args.test_text)

    elif args.test_image:
        p = Path(args.test_image)
        if not p.is_file():
            sys.exit(f"Immagine non trovata: {p}")
        img_b64 = resize_image_base64(p, cfg["preprocessing"].get("image_max_side_px", 512))
        file_saved = str(p)
        state_text = "Immagine salvata su Telegram."
        print(f"Immagine caricata: {p} ({len(img_b64)} chars base64)")

    t0 = time.time()
    res = run_decision(state_text, img_b64, cfg)
    elapsed = round(time.time() - t0, 2)
    cmd = synthesize_command(res, urls, file_saved, state_text)

    print(f"Risultato in {elapsed}s:")
    print(f"  • Categoria   : {res['nome_classe']} ({res['categoria']})")
    print(f"  • Confidenza  : {res['confidence'] * 100:.1f}%")
    print(f"  • Destinazione: {res['destinazione']}")
    print(f"  • Azione      : {res['proposta']}")
    print(f"  • Comando     : {cmd or '(Nessun comando sintetizzato)'}")
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

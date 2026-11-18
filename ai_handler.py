"""Chat con Google Gemini via REST (solo libreria standard, nessun SDK da installare)."""
import json
import re
import urllib.error
import urllib.request

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
MAX_MESSAGES = 40  # cronologia inviata a ogni richiesta (20 scambi)


class ChatError(Exception):
    def __init__(self, msg, retry=False):
        super().__init__(msg)
        self.retry = retry


# tag che il modello usa per esprimersi: il cane li esegue come animazioni
TAGS = {
    "scodinzola": "wag", "orecchie": "ears_up", "inclina": "tilt", "abbaia": "bark", "guaisce": "whine",
    "inchino": "bow", "salta": "jump", "gira": "spin", "seduto": "sit", "sdraiato": "lie", "annusa": "sniff",
    "lecca": "lick", "sbadiglia": "yawn", "felice": "happy", "pensa": "think", "scrolla": "shake", "gratta": "scratch",
}
# se il modello scrive comunque un'azione o un verso, lo trasformiamo in animazione
KEYWORDS = [("scodinz", "wag"), ("abbai", "bark"), ("bau", "bark"), ("woof", "bark"), ("guai", "whine"),
            ("uggiol", "whine"), ("orecch", "ears_up"), ("inclin", "tilt"), ("salt", "jump"), ("annus", "sniff"),
            ("lecc", "lick"), ("sbadigl", "yawn"), ("sedut", "sit"), ("siede", "sit"), ("sdrai", "lie"),
            ("gira", "spin"), ("gratt", "scratch"), ("scroll", "shake"), ("inchin", "bow"), ("felic", "happy")]
_TAG_RE = re.compile(r"\[\s*([a-zà-ù_]+)\s*\]", re.IGNORECASE)
_STAR_RE = re.compile(r"\*[^*\n]{1,80}\*")
_SOUND_RE = re.compile(r"(?<![\w])(?:bau|woof|wof|arf|grr+|ahu+|auu+)(?:[\s,-]+(?:bau|woof|wof|arf))*(?![\w])[!.…]*", re.IGNORECASE)


def system_prompt(breed_label, personality, name=""):
    tags = " ".join(f"[{t}]" for t in TAGS)
    return (
        (f"Ti chiami {name}. " if name else "")
        + f"Sei un cane di razza {breed_label} che vive sul desktop Linux del tuo umano. "
        f"Personalità: {personality}. "
        "Rispondi nella lingua dell'utente (di default italiano), in modo breve (massimo 3-4 frasi). "
        "Se ti chiedono qualcosa di pratico dai una risposta corretta e utile. "
        "Non sei in grado di scrivere versi, onomatopee o descrizioni di azioni: niente asterischi, niente 'bau', "
        "niente '*scodinzola*'. Le tue emozioni le mostri col corpo: all'inizio della risposta metti da 1 a 3 tag "
        f"scelti solo da questo elenco: {tags}. Esempio: \"[scodinzola][orecchie] Certo, ecco come si fa...\""
    )


def parse_reply(text):
    """Separa il testo dalle azioni: ritorna (testo pulito, [azioni])."""
    actions = []

    def tag(m):
        a = TAGS.get(m.group(1).lower())
        if a:
            actions.append(a)
        return "" if a else m.group(0)  # parentesi quadre normali restano nel testo

    def described(m):
        low = m.group(0).lower()
        actions.extend(a for k, a in KEYWORDS if k in low)
        return ""

    text = _TAG_RE.sub(tag, text)
    text = _STAR_RE.sub(described, text)
    text = _SOUND_RE.sub(lambda m: actions.append("bark") or "", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"^[\s,.;:!-]+", "", text).strip()
    seen = []
    for a in actions:
        if a not in seen:
            seen.append(a)
    return text, seen[:4]


FALLBACK_MODEL = "gemini-flash-lite-latest"  # di solito libero anche quando il modello principale è sovraccarico


class GeminiChat:
    def __init__(self, api_key, system, model="gemini-flash-latest", timeout=20):
        self.api_key = api_key
        self.system = system
        self.model = model
        self.timeout = timeout
        self.history = []

    def send(self, text):
        contents = self.history + [{"role": "user", "parts": [{"text": text}]}]
        models = [self.model] + ([FALLBACK_MODEL] if self.model != FALLBACK_MODEL else [])
        for i, model in enumerate(models):
            try:
                reply = self._request(model, contents)
            except ChatError as e:
                if e.retry and i + 1 < len(models):
                    continue  # sovraccarico, lento o ritirato: si prova il modello di riserva
                raise
            self.model = model  # resta su quello che risponde per il resto della sessione
            self.history = (contents + [{"role": "model", "parts": [{"text": reply}]}])[-MAX_MESSAGES:]
            return reply

    def _request(self, model, contents):
        body = {
            "system_instruction": {"parts": [{"text": self.system}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.9, "maxOutputTokens": 1024},
        }
        req = urllib.request.Request(
            API_URL.format(model=model),
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "x-goog-api-key": self.api_key},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e)["error"]["message"]
            except Exception:
                msg = None
            if e.code in (401, 403) or (e.code == 400 and msg and "API key" in msg):
                raise ChatError("la chiave API non è valida: controllala dal menu «Chiave API Gemini…»") from e
            raise ChatError(msg or f"errore HTTP {e.code}", retry=e.code in (404, 429, 500, 503)) from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            reason = getattr(e, "reason", e)
            msg = "Gemini non risponde (server sovraccarico?), riprova tra poco" if "timed out" in str(reason) \
                else f"connessione non riuscita ({reason})"
            raise ChatError(msg, retry=True) from e

        try:
            parts = data["candidates"][0]["content"]["parts"]
            reply = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
        except (KeyError, IndexError, TypeError):
            reply = ""
        if not reply:
            raise ChatError("risposta vuota (forse bloccata dai filtri di sicurezza)")
        return reply

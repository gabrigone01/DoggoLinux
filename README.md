# Doggo 🐕

Un cane in 3D che vive sui tuoi schermi: passeggia, si gira, ti guarda, si fa gli affari suoi, gioca con te, dorme nella sua cuccia e chiacchiera con te tramite Google Gemini. Funziona su **Linux**, **Windows** e **macOS**.

Tutti i file si scaricano dalla pagina [Releases](https://github.com/gabrigone01/DoggoLinux/releases/latest). Serve una scheda video con OpenGL 4.1 (va bene qualsiasi GPU integrata recente).

## Installazione su Linux (Ubuntu, Kubuntu, Debian)

Ubuntu 24.04 o successivo.

1. **Scarica** [doggo_all.deb](https://github.com/gabrigone01/DoggoLinux/releases/latest/download/doggo_all.deb), oppure da terminale:

   ```bash
   wget https://github.com/gabrigone01/DoggoLinux/releases/latest/download/doggo_all.deb
   ```

2. **Installa** (apt scarica da solo le dipendenze: PyQt6 e le librerie grafiche):

   ```bash
   sudo apt install ./doggo_all.deb
   ```

3. **Avvia**: menu Applicazioni → Giochi → **Doggo**, oppure scrivi `doggo` nel terminale.

**Aggiornare**: scarica il nuovo `doggo_all.deb` e ripeti il punto 2.
**Disinstallare**: `sudo apt remove doggo` (le impostazioni restano in `~/.config/doggo`).

## Installazione su Windows

Windows 10 o 11.

1. **Scarica** [Doggo-windows.exe](https://github.com/gabrigone01/DoggoLinux/releases/latest/download/Doggo-windows.exe) e mettilo dove vuoi (per esempio in `Documenti\Doggo`).
2. **Avvia** con un doppio clic. Il programma non è firmato digitalmente, quindi al primo avvio Windows SmartScreen può mostrare «Windows ha protetto il PC»: clicca **Ulteriori informazioni → Esegui comunque**.
3. Il primo avvio richiede qualche secondo (il programma si scompatta).

**Disinstallare**: togli l'avvio automatico dal menu del cane, poi cancella `Doggo-windows.exe` e la cartella `%APPDATA%\Doggo`.

## Installazione su macOS

macOS 12 o successivo, Mac con processore Apple (M1, M2, M3, …).

1. **Scarica** [Doggo-macos.zip](https://github.com/gabrigone01/DoggoLinux/releases/latest/download/Doggo-macos.zip) e aprilo: compare **Doggo.app**.
2. **Trascina** Doggo.app nella cartella **Applicazioni**.
3. **Primo avvio**: l'app non è firmata da Apple, quindi fai clic destro (o Ctrl+clic) su Doggo.app → **Apri** → **Apri**. Se macOS la blocca comunque: Impostazioni di Sistema → Privacy e sicurezza → **Apri comunque**.

**Disinstallare**: togli l'avvio automatico dal menu del cane, poi sposta Doggo.app nel Cestino e cancella `~/Library/Application Support/Doggo`.

## Dopo l'installazione (tutti i sistemi)

- **Avvio automatico all'accensione**: clic destro sul cane → **«Avvia all'accensione del PC»**. Da lì si può anche togliere.
- **Chat**: clic destro sul cane → «Chiave API Gemini…» e incolla una chiave gratuita presa su <https://aistudio.google.com/apikey>.
- Se apri il programma due volte resta comunque un solo cane.
- Sedersi sulle finestre e tirarle funziona solo su Linux con KDE Plasma; il resto funziona ovunque.

## Avvio dal codice sorgente

```bash
git clone https://github.com/gabrigone01/DoggoLinux.git
cd DoggoLinux
sudo apt install python3-pyqt6 libxcb-cursor0   # Linux; su Windows/macOS: pip install PyQt6
python3 main.py
```

Gemini si usa con chiamate REST dirette: non serve installare nessun SDK.

## Pubblicare una nuova versione

A ogni tag `v…` GitHub Actions costruisce `.deb` (Linux), `.exe` (Windows) e `.app` (macOS) e li allega alla Release (`.github/workflows/release.yml`):

```bash
git tag v1.0.1
git push origin v1.0.1
```

Per costruirlo in locale: `sh packaging/build-deb.sh 1.0.1` → `build/doggo_all.deb`.

## Cosa fa

- **Ispirato ai Maremmani veri**: pelo avorio lungo che cade a ciocche, criniera, coda folta portata bassa, orecchie a V color biscotto, naso e labbra neri, bocca aperta che ansima.
- **3D in tempo reale**: il cane è disegnato dalla scheda video (ray marching di forme organiche) con scheletro, zampe articolate, pelo, luci e ombra a terra. Cammina col passo vero, si gira, si siede, si sdraia, dorme.
- **Si fa gli affari suoi**: passeggia, annusa per terra, mangia dalla ciotola accanto alla cuccia, gioca da solo con la pallina, scava, ulula, si rotola sulla schiena, fa le corse pazze, salta, si gratta, si stiracchia, si scrolla, si rincorre la coda, va a esplorare gli altri schermi o torna a dormire nella cuccia. Shiba e Maremmano sono più indipendenti, Border Collie e Golden più attenti a te.
- **Gioca con le finestre** (KDE): sa dove sono le tue finestre. Preferisce stare sul desktop libero, ogni tanto salta sul bordo superiore di una finestra e ci si siede o sdraia (se la sposti la segue, se la chiudi scende con un salto), oppure addenta il bordo di una finestra e la tira un po' di lato camminando all'indietro. Non tocca mai finestre massimizzate o a schermo intero. Si spegne dal menu «Gioca con le finestre».
- **Ti vede**: segue con lo sguardo il mouse quando lo muovi vicino a lui.
- **Lo chiami**:
  - clic sinistro sul cane: si ferma, si gira verso di te, ti guarda e apre il fumetto della chat;
  - scuoti il mouse a destra e sinistra: corre sotto al cursore, anche su un altro schermo, e ti guarda.
- **Tutto lo schermo**: gli schermi sono un pavimento visto in prospettiva: il cane cammina ovunque (salendo si allontana e ti mostra la schiena, scendendo viene verso di te; per le mete in verticale procede a zig-zag in diagonale) e passa da uno schermo all'altro attraverso i bordi in comune.
- **Chat**: risponde con la personalità della razza. Le emozioni non sono scritte ma recitate: abbaia, scodinzola, inclina la testa, guaisce, fa l'inchino, salta, sbadiglia…

| Azione | Effetto |
|---|---|
| Clic sinistro sul cane | Ti guarda e apre/chiude la chat (Invio per inviare, Esc per chiudere) |
| Clic con la rotella sul cane | Carezza: si gode le coccole a occhi chiusi, ti dà la zampa o si mette a pancia all'aria |
| Clic destro → «Tira rametto» / «Lancia pallina» | Clicchi un punto qualsiasi degli schermi: il giocattolo vola lì e cade a terra, il cane lo rincorre, lo prende in bocca e te lo riporta |
| Clic destro → «Nome del cane…» | Gli dai un nome: lo usa in chat, e se lo scrivi drizza le orecchie |
| Clic sinistro sulla cuccia | Il cane corre veloce alla cuccia e si sdraia davanti alla porta |
| Trascinare la cuccia | La sposti dove vuoi, in qualunque punto degli schermi (la posizione viene ricordata). Di base sta in un angolo, un po' staccata dal fondo |
| Clic destro su cane o cuccia | Menu: razza, cuccia nell'angolo, torna nella cuccia, chiave API, esci |
| Scuotere il mouse | Il cane corre da te |

Il resto dello schermo resta cliccabile: le finestre accettano clic solo dove c'è il cane o la cuccia.

## Wayland (KDE Plasma)

Su Wayland un'app non può vedere il mouse fuori dalle proprie finestre. All'avvio il cane carica un piccolo script KWin (`doggo-desktop-pet`) che gli passa via D-Bus la posizione del cursore e le aree utili di ogni schermo (pannelli esclusi) e la posizione delle finestre, e sposta la finestra che il cane sta tirando. Alla chiusura lo script viene rimosso. Le finestre usano XWayland per potersi posizionare e restare sopra le altre.

Su una sessione X11 lo script non serve e il cursore si legge direttamente.

## Chiave API Gemini

Se il modello scelto è sovraccarico, lento o ritirato, il cane passa da solo a `gemini-flash-lite-latest`.

Crea una chiave gratuita su <https://aistudio.google.com/apikey>, poi:

- esporta `GEMINI_API_KEY=...` (ha la precedenza), **oppure**
- clic destro sul cane → «Chiave API Gemini…»: viene salvata nelle impostazioni (`~/.config/doggo/config.json` su Linux, `%APPDATA%\\Doggo` su Windows, `~/Library/Application Support/Doggo` su macOS).

## Impostazioni (`config.json`)

```json
{ "breed": "maremmano", "name": "", "kennel": "right", "windows": true, "api_key": "", "model": "gemini-flash-latest" }
```

`breed`: `maremmano`, `golden`, `collie`, `dachshund`, `shiba`. `kennel`: `right` o `left` (angolo dello schermo principale). Quando trascini la cuccia si aggiunge `kennel_pos` con la sua posizione.

## File

- `main.py`: finestre, ciclo principale, chat e menu
- `brain.py`: comportamento (attività autonome, sguardo, richiami, azioni, spostamenti tra schermi)
- `dog3d.py`: razze, scheletro e pose del cane
- `dog.frag`: shader che disegna cane e cuccia in 3D
- `view3d.py`: finestre OpenGL trasparenti
- `kwin_bridge.py`: cursore e schermi da KWin su Wayland
- `ai_handler.py`: client Gemini e traduzione delle emozioni in azioni
- `packaging/build-deb.sh`: costruisce il pacchetto `.deb`
- `test_pet.py`: test (`python3 test_pet.py`)

## Limiti noti

- Con il ridimensionamento schermo diverso dal 100% le coordinate del cursore di KWin e quelle di XWayland possono non coincidere.
- Niente suoni: l'abbaiare si vede ma non si sente.
- Le versioni Windows e macOS non sono firmate digitalmente (vedi gli avvisi al primo avvio).
- macOS: solo Mac con processore Apple; per i Mac Intel si può avviare dal codice sorgente.

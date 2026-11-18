#!/bin/sh
# Costruisce il pacchetto .deb: sh packaging/build-deb.sh [versione]  →  build/doggo_all.deb
set -eu
VERSION="${1:-1.0.0}"
VERSION="${VERSION#v}"
cd "$(dirname "$0")/.."
ROOT="build/doggo"
rm -rf build
mkdir -p "$ROOT/DEBIAN" "$ROOT/usr/share/doggo" "$ROOT/usr/bin" "$ROOT/usr/share/applications" \
         "$ROOT/usr/share/icons/hicolor/256x256/apps"

cp main.py brain.py dog3d.py view3d.py kwin_bridge.py ai_handler.py sounds.py dog.frag icon.png "$ROOT/usr/share/doggo/"
cp icon.png "$ROOT/usr/share/icons/hicolor/256x256/apps/doggo.png"

cat > "$ROOT/usr/bin/doggo" <<'SH'
#!/bin/sh
export PYTHONDONTWRITEBYTECODE=1
exec python3 /usr/share/doggo/main.py "$@"
SH
chmod 755 "$ROOT/usr/bin/doggo"

cat > "$ROOT/usr/share/applications/doggo.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=Doggo
GenericName=Cane da scrivania
Comment=Un cane in 3D che vive sui tuoi schermi e chiacchiera con te
Exec=doggo
Icon=doggo
Terminal=false
StartupNotify=false
Categories=Game;Amusement;
Keywords=cane;dog;pet;maremmano;
DESKTOP

cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: doggo
Version: $VERSION
Section: games
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-pyqt6, libxcb-cursor0, libgl1
Maintainer: gabrigone01 <gabrigone01@users.noreply.github.com>
Homepage: https://github.com/gabrigone01/DoggoLinux
Description: cane 3D da scrivania che chiacchiera con Google Gemini
 Un Pastore Maremmano (o un'altra razza) in 3D che vive sugli schermi:
 passeggia, gioca, si siede sulle finestre, riporta il rametto e
 chiacchiera tramite le API di Google Gemini.
CONTROL

find "$ROOT" -type d -exec chmod 755 {} +
find "$ROOT/usr/share" -type f -exec chmod 644 {} +
dpkg-deb --root-owner-group --build "$ROOT" build/doggo_all.deb
echo "Pacchetto pronto: build/doggo_all.deb (versione $VERSION)"

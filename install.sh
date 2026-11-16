#!/bin/sh
# kick-bot Linux kurulumu: son sürümü indirir ve uygulama menüsüne ekler. Güncellemek için yeniden çalıştır.
set -eu
REPO="caferozpinar/KickChatbot"
BIN="$HOME/.local/bin/kick-bot"
mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
echo "kick-bot indiriliyor..."
curl -fL "https://github.com/$REPO/releases/latest/download/kick-bot-linux" -o "$BIN.tmp"
chmod +x "$BIN.tmp"
mv "$BIN.tmp" "$BIN"
cat > "$HOME/.local/share/applications/kick-bot.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=kick-bot
Comment=Kick chat moderasyon botu
Exec=$BIN
Terminal=false
Categories=Network;
DESKTOP
echo "Kuruldu. Uygulama menüsünden 'kick-bot' ile aç ya da şunu çalıştır: $BIN"

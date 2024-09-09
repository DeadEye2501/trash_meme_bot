# Trash Meme Bot

Этот бот существует для того, чтобы сделать вашу переписку в телеграме с друзьями, где вы скидываете друг другу мемы,
более интерактивной и похожей на ленту. Просто добавьте бота в группу и дайте ему права администратора.

### Установка

`pip install -r requirements.txt` - установка зависимостей
`playwright install` - после установки зависимостей
копировать файл `.env`
копировать файл `meme_bot.service` в `/etc/systemd/system/`

### Управление

`sudo systemctl start trash_meme_bot` - запуск бота
`sudo systemctl stop trash_meme_bot` - остановка бота
`sudo systemctl restart trash_meme_bot` - перезапуск бота
`sudo systemctl status trash_meme_bot` - статус бота
`sudo journalctl -u trash_meme_bot.service -b` - подробные логи
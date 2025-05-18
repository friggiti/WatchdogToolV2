import sys
import os
import httpx
import asyncio
import threading
import random
import time
import json
import csv
import statistics
import concurrent.futures
import functools
import subprocess
import tempfile
import atexit
from queue import Queue
from datetime import datetime
from typing import List, Dict, Any, Optional, Union, Tuple, Callable
from concurrent.futures import ThreadPoolExecutor
from asyncio import Semaphore, create_task, gather, get_event_loop, new_event_loop, set_event_loop
import platform
from functools import lru_cache
from PyQt5.QtWidgets import (QApplication, QMainWindow, QComboBox, QLineEdit, 
                             QPushButton, QTextEdit, QVBoxLayout, QHBoxLayout, 
                             QLabel, QWidget, QMessageBox, QSpinBox, QProgressBar,
                             QGroupBox, QGridLayout, QCheckBox, QFileDialog,
                             QTabWidget, QRadioButton, QButtonGroup, QDoubleSpinBox,
                             QStyleFactory, QFrame, QSizePolicy)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, QPropertyAnimation, QEasingCurve, QRect, QSize, QEvent
from PyQt5.QtGui import QColor, QPalette, QFont

# Try to import win10toast for Windows notifications
try:
    from win10toast import ToastNotifier
    HAS_WIN10TOAST = True
except ImportError:
    HAS_WIN10TOAST = False
class CliDebugConsole:
    """CLI Debug console that runs in a separate command prompt window"""
    
    # Color codes for Windows console
    COLORS = {
        "RESET": "",        # Windows CMD doesn't support ANSI reset by default
        "RED": "color 0C",  # Red text
        "GREEN": "color 0A", # Green text
        "YELLOW": "color 0E", # Yellow text
        "BLUE": "color 09", # Blue text
        "MAGENTA": "color 0D", # Magenta text
        "CYAN": "color 0B", # Cyan text
        "WHITE": "color 0F" # White text
    }
    
    def __init__(self):
        self.process = None
        self.command_file = None
        self.debug_file_path = None
        self.initialize_console()
        
    def initialize_console(self):
        """Start a new command prompt window for debug output"""
        try:
            # Create a temporary batch file to keep the console window open
            fd, self.debug_file_path = tempfile.mkstemp(suffix='.bat')
            with os.fdopen(fd, 'w') as f:
                # Write the ASCII logo to the batch file
                f.write('@echo off\n')
                f.write('cls\n')
                f.write('echo.\n')
                f.write('echo __        ___  _____ ____ _   _ ____   ___   ____\n')
                f.write('echo \\ \\      / / \\|_   _/ ___| | | |  _ \\ / _ \\ / ___|\n')
                f.write('echo  \\ \\ /\\ / / _ \\ | || |   | |_| | | | | | | | |  _\n')
                f.write('echo   \\ V  V / ___ \\| || |___|  _  | |_| | |_| | |_| |\n')
                f.write('echo    \\_/\\_/_/   \\_\\_| \\____|_| |_|____/ \\___/ \\____|\n')
                f.write('echo.\n')
                f.write('echo Watchdog Debug Console\n')
                f.write('echo -----------------------\n')
                f.write('echo.\n')
                f.write('color 0B\n')  # Cyan color for the header
                f.write('title Watchdog Debug Console\n')
                # This loop keeps the window open and checks for commands
                f.write('echo Waiting for requests to start...\n')
                f.write('echo.\n')
                
                # Create a command file that we'll write to for controlling the console
                fd_cmd, cmd_file = tempfile.mkstemp(suffix='.txt')
                self.command_file = cmd_file
                os.close(fd_cmd)
                
                # Add a loop to continuously check for commands
                f.write(f'for /F "tokens=*" %%A in (\'{cmd_file}\') do (\n')
                f.write('  echo %%A\n')
                f.write('  ping -n 2 127.0.0.1 > nul\n')  # Small delay
                f.write(')\n')
                
                # Keep window open
                f.write('echo Press any key to close this window...\n')
                f.write('pause > nul\n')

            # Launch the console window with the batch file
            if platform.system() == "Windows":
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                startupinfo.wShowWindow = 1  # SW_SHOWNORMAL
                
                self.process = subprocess.Popen(
                    [self.debug_file_path],
                    startupinfo=startupinfo,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )
            else:
                # For non-Windows platforms
                self.process = subprocess.Popen(
                    ["bash", self.debug_file_path],
                    shell=False
                )
            
            # Register cleanup function
            atexit.register(self.cleanup)
            
            # Clear the command file
            with open(self.command_file, 'w') as f:
                pass
                
        except Exception as e:
            print(f"Error initializing debug console: {e}")
    
    def send_message(self, message, color=None):
        """Send a message to the console window"""
        if not self.process or not self.command_file:
            return
            
        try:
            color_cmd = ""
            if color and color in self.COLORS:
                color_cmd = self.COLORS[color] + "\n"
                
            with open(self.command_file, 'a') as f:
                if color_cmd:
                    f.write(color_cmd)
                f.write(message + "\n")
                if color_cmd:
                    f.write(self.COLORS["WHITE"] + "\n") # Reset to white
        except Exception as e:
            print(f"Error sending message to debug console: {e}")
    
    def update_status(self, url, total, success, failed, rate):
        """Update the status in the console window"""
        status_msg = f"URL: {url} | Total: {total} | Success: {success} | Failed: {failed} | Rate: {rate:.2f}/sec"
        self.send_message("\n" + status_msg, "CYAN")
    
    def cleanup(self):
        """Clean up resources when the application exits"""
        try:
            # Kill the process
            if self.process:
                self.process.terminate()
                
            # Delete temporary files
            if self.debug_file_path and os.path.exists(self.debug_file_path):
                os.unlink(self.debug_file_path)
                
            if self.command_file and os.path.exists(self.command_file):
                os.unlink(self.command_file)
        except Exception as e:
            print(f"Error cleaning up debug console: {e}")

class WatchdogTool(QMainWindow):
    # Signals for updating the UI from worker threads
    update_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    status_signal = pyqtSignal(str, str)  # status, color
    debug_signal = pyqtSignal(str, str)  # debug message and color for console
    
    # Color scheme
    COLORS = {
        "primary": "#2979FF",
        "secondary": "#651FFF",
        "success": "#00C853",
        "warning": "#FF9100",
        "error": "#FF1744",
        "info": "#00B0FF",
        "dark": "#424242",
        "light": "#F5F5F5",
        "background": "#FFFFFF",
        "text": "#212121"
    }
    
    def __init__(self):
        super().__init__()
        self.request_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.active_threads = 0
        self.stop_requested = False
        self.start_time = None
        self.response_times = []
        self.executor = None
        self.session = None
        self.loop = None
        self.retry_count = 3  # Default retries
        self.response_cache = {}  # Cache for similar responses
        self.animations = []  # Store animations to prevent garbage collection
        self.save_path = ""
        self.save_results = False
        
        # Set application style
        self.apply_stylesheet()
        
        # Create CLI debug console
        self.debug_console = CliDebugConsole()
        
        # Initialize UI components
        self.initUI()
        
        # Send startup message to debug console
        self.debug_console.send_message("[INFO] Watchdog application started", "GREEN")
        
    def apply_stylesheet(self):
        """Apply custom style settings to the application"""
        # Set application style to Fusion for a modern look
        QApplication.setStyle(QStyleFactory.create("Fusion"))
        
        # Create a custom palette
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(self.COLORS["background"]))
        palette.setColor(QPalette.WindowText, QColor(self.COLORS["text"]))
        palette.setColor(QPalette.Base, QColor(self.COLORS["light"]))
        palette.setColor(QPalette.AlternateBase, QColor(self.COLORS["background"]))
        palette.setColor(QPalette.ToolTipBase, QColor(self.COLORS["dark"]))
        palette.setColor(QPalette.ToolTipText, QColor(self.COLORS["light"]))
        palette.setColor(QPalette.Text, QColor(self.COLORS["text"]))
        palette.setColor(QPalette.Button, QColor(self.COLORS["background"]))
        palette.setColor(QPalette.ButtonText, QColor(self.COLORS["text"]))
        palette.setColor(QPalette.Highlight, QColor(self.COLORS["primary"]))
        palette.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
        
        # Apply palette
        QApplication.setPalette(palette)
    
    def send_debug_message(self, message, color):
        """Send a message to the CLI debug console"""
        self.debug_console.send_message(message, color)
    
    def show_notification(self, title, message, duration=5):
        """Show a system notification"""
        # Show Windows toast notification if available
        if HAS_WIN10TOAST and platform.system() == "Windows":
            try:
                toaster = ToastNotifier()
                toaster.show_toast(title, message, duration=duration, threaded=True)
            except Exception as e:
                print(f"Failed to show toast notification: {e}")
                
        # Fallback to console notification if toast fails or isn't available
        self.debug_console.send_message(f"\n[NOTIFICATION] {title}: {message}", "MAGENTA")
    
    def initUI(self):
        """Initialize the UI components"""
        self.setWindowTitle("Watchdog - Advanced Request Tool")
        self.setGeometry(100, 100, 1000, 800)
        
        # Main widget and layout
        main_widget = QWidget()
        main_layout = QVBoxLayout()
        
        # URL input section
        url_layout = QHBoxLayout()
        url_label = QLabel("URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter URL (e.g., https://example.com)")
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        
        # User Agent selection section
        ua_layout = QHBoxLayout()
        ua_label = QLabel("User Agent:")
        self.ua_combo = QComboBox()
        
        # Add extensive list of user agents
        self.user_agents = {
            # Chrome versions
            "Chrome (Windows)": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Chrome (Windows) 94": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Safari/537.36",
            "Chrome (Windows) 95": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.69 Safari/537.36",
            "Chrome (Windows) 96": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.45 Safari/537.36",
            "Chrome (macOS)": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
            "Chrome (Linux)": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
            
            # Firefox versions
            "Firefox (Windows)": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Firefox (Windows) 90": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:90.0) Gecko/20100101 Firefox/90.0",
            "Firefox (Windows) 91": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:91.0) Gecko/20100101 Firefox/91.0",
            "Firefox (Windows) 92": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:92.0) Gecko/20100101 Firefox/92.0",
            "Firefox (macOS)": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Firefox (Linux)": "Mozilla/5.0 (X11; Linux x86_64; rv:89.0) Gecko/20100101 Firefox/89.0",
            
            # Edge versions
            "Edge (Windows)": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59",
            "Edge (Windows) 94": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.81 Safari/537.36 Edg/94.0.992.47",
            "Edge (Windows) 95": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.54 Safari/537.36 Edg/95.0.1020.30",
            "Edge (macOS)": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59",
            
            # Safari versions
            "Safari (macOS)": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15",
            "Safari (macOS) 15": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Safari/605.1.15",
            "Safari (iOS)": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1",
            "Safari (iOS) 15": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
            
            # Mobile browsers
            "Chrome (Android)": "Mozilla/5.0 (Linux; Android 10; SM-A205U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.120 Mobile Safari/537.36",
            "Chrome (Android) 94": "Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/94.0.4606.71 Mobile Safari/537.36",
            "Firefox (Android)": "Mozilla/5.0 (Android 12; Mobile; rv:93.0) Gecko/93.0 Firefox/93.0",
            "Samsung Browser": "Mozilla/5.0 (Linux; Android 10; SAMSUNG SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/14.2 Chrome/87.0.4280.141 Mobile Safari/537.36",
            "UC Browser": "Mozilla/5.0 (Linux; U; Android 10; en-US; SM-G973F) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/78.0.3904.108 UCBrowser/13.3.8.1305 Mobile Safari/537.36",
            
            # Bots and crawlers
            "Googlebot": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "Bingbot": "Mozilla/5.0 (compatible; Bingbot/2.0; +http://www.bing.com/bingbot.htm)",
            "Yandexbot": "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
            "DuckDuckBot": "DuckDuckBot/1.0; (+http://duckduckgo.com/duckduckbot.html)",
            
            # Other browsers
            "Opera (Windows)": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 OPR/77.0.4054.254",
            "Opera (macOS)": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 OPR/77.0.4054.254",
            "Brave (Windows)": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Brave/1.27.111",
            "Vivaldi (Windows)": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Vivaldi/4.0",
            
            # Desktop applications
            "Electron": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) electron/13.1.7 Chrome/91.0.4472.124 Electron/13.1.7 Safari/537.36",
            "Postman": "PostmanRuntime/7.28.2",
            
            # Game consoles
            "PlayStation 5": "Mozilla/5.0 (PlayStation; PlayStation 5/1.0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0 Safari/605.1.15",
            "Xbox Series X": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; Xbox; Xbox Series X) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edge/91.0.864.59",
            
            # TV browsers
            "Samsung TV": "Mozilla/5.0 (SMART-TV; LINUX; Tizen 5.5) AppleWebKit/537.36 (KHTML, like Gecko) Version/5.5 TV Safari/537.36",
            "Apple TV": "AppleTV6,2/11.1",
            
            # Old browsers (for testing compatibility)
            "IE 11": "Mozilla/5.0 (Windows NT 10.0; WOW64; Trident/7.0; rv:11.0) like Gecko",
            "IE 9": "Mozilla/5.0 (compatible; MSIE 9.0; Windows NT 6.1; Trident/5.0)",
            "Firefox 52 ESR": "Mozilla/5.0 (Windows NT 6.1; WOW64; rv:52.0) Gecko/20100101 Firefox/52.0",
            
            # Security tools
            "ZAP": "Mozilla/5.0 (compatible; OWASP ZAP/2.10.0; +https://www.zaproxy.org)",
            "Burp Suite": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            
            # Additional browsers
            "Chrome 98": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
            "Chrome 99": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36",
            "Firefox 97": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:97.0) Gecko/20100101 Firefox/97.0",
            "Firefox 98": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:98.0) Gecko/20100101 Firefox/98.0",
            "Edge 99": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/99.0.4844.51 Safari/537.36 Edg/99.0.1150.30",
            "Safari 15.4": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.4 Safari/605.1.15",
            "Custom": "Custom User Agent"
        }
        for agent_name in self.user_agents.keys():
            self.ua_combo.addItem(agent_name)
            
        self.custom_ua_input = QLineEdit()
        self.custom_ua_input.setPlaceholderText("Enter custom user agent")
        self.custom_ua_input.setEnabled(False)
        
        # Connect the combo box to enable/disable custom input
        self.ua_combo.currentTextChanged.connect(self.on_ua_changed)
        
        ua_layout.addWidget(ua_label)
        ua_layout.addWidget(self.ua_combo)
        
        custom_ua_layout = QHBoxLayout()
        custom_ua_layout.addWidget(QLabel("Custom:"))
        custom_ua_layout.addWidget(self.custom_ua_input)
        
        # Request configuration section
        config_group = QGroupBox("Request Configuration")
        config_layout = QGridLayout()
        
        # Number of user agents
        ua_count_label = QLabel("Number of User Agents:")
        self.ua_count_spin = QSpinBox()
        self.ua_count_spin.setRange(1, len(self.user_agents) - 1)  # Exclude "Custom"
        self.ua_count_spin.setValue(1)
        self.ua_count_spin.setToolTip("Number of different user agents to use (randomly selected)")
        config_layout.addWidget(ua_count_label, 0, 0)
        config_layout.addWidget(self.ua_count_spin, 0, 1)
        
        # Number of threads
        threads_label = QLabel("Number of Threads:")
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 500)  # Increased to 500 threads max
        self.threads_spin.setValue(20)
        self.threads_spin.setToolTip("Number of concurrent requests (1-500)")
        config_layout.addWidget(threads_label, 0, 2)
        config_layout.addWidget(self.threads_spin, 0, 3)
        
        # Number of requests
        requests_label = QLabel("Number of Requests:")
        self.requests_spin = QSpinBox()
        self.requests_spin.setRange(1, 10000)  # Maximum 10000 requests
        self.requests_spin.setValue(100)
        self.requests_spin.setToolTip("Total number of requests to send (1-10000)")
        config_layout.addWidget(requests_label, 1, 0)
        config_layout.addWidget(self.requests_spin, 1, 1)
        
        # Request timeout
        timeout_label = QLabel("Timeout (seconds):")
        self.timeout_spin = QSpinBox()
        self.timeout_spin.setRange(1, 120)
        self.timeout_spin.setValue(30)
        self.timeout_spin.setToolTip("Request timeout in seconds")
        config_layout.addWidget(timeout_label, 1, 2)
        config_layout.addWidget(self.timeout_spin, 1, 3)
        
        # HTTP Method
        method_label = QLabel("HTTP Method:")
        self.method_combo = QComboBox()
        for method in ["GET", "POST", "HEAD", "PUT", "DELETE", "OPTIONS"]:
            self.method_combo.addItem(method)
        config_layout.addWidget(method_label, 2, 0)
        config_layout.addWidget(self.method_combo, 2, 1)
        
        # Rate limiting
        rate_limit_label = QLabel("Rate Limit (req/sec):")
        self.rate_limit_spin = QDoubleSpinBox()
        self.rate_limit_spin.setRange(0.1, 1000)
        self.rate_limit_spin.setValue(10.0)
        self.rate_limit_spin.setSingleStep(1.0)
        self.rate_limit_spin.setToolTip("Maximum requests per second (0.1-1000)")
        config_layout.addWidget(rate_limit_label, 2, 2)
        config_layout.addWidget(self.rate_limit_spin, 2, 3)
        
        # Delay between requests
        delay_label = QLabel("Delay (seconds):")
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.0, 10.0)
        self.delay_spin.setValue(0.0)
        self.delay_spin.setSingleStep(0.1)
        self.delay_spin.setToolTip("Additional delay between requests")
        config_layout.addWidget(delay_label, 3, 0)
        config_layout.addWidget(self.delay_spin, 3, 1)
        
        # Connection pooling settings
        pool_label = QLabel("Connection Pool Size:")
        self.pool_spin = QSpinBox()
        self.pool_spin.setRange(1, 1000)
        self.pool_spin.setValue(100)
        self.pool_spin.setToolTip("Size of connection pool for aiohttp")
        config_layout.addWidget(pool_label, 3, 2)
        config_layout.addWidget(self.pool_spin, 3, 3)
        
        config_group.setLayout(config_layout)
        
        # Progress section
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        progress_layout.setSpacing(10)
        progress_layout.setContentsMargins(10, 15, 10, 10)
        
        self.status_label = QLabel("Status: Ready")
        self.status_label.setFont(QFont("Segoe UI", 9, QFont.Bold))
        self.status_label.setStyleSheet(f"color: {self.COLORS['info']};")
        progress_layout.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("%v/%m (%p%)")
        progress_layout.addWidget(self.progress_bar)
        
        self.stats_label = QLabel("Statistics: Ready")
        self.stats_label.setWordWrap(True)
        progress_layout.addWidget(self.stats_label)
        
        # Add save results checkbox
        save_layout = QHBoxLayout()
        self.save_checkbox = QCheckBox("Save results to file")
        self.save_checkbox.setChecked(False)
        self.save_path_button = QPushButton("Select File...")
        self.save_path_button.clicked.connect(self.select_save_file)
        self.save_path_label = QLabel("No file selected")
        self.save_path = ""
        
        save_layout.addWidget(self.save_checkbox)
        save_layout.addWidget(self.save_path_button)
        save_layout.addWidget(self.save_path_label)
        progress_layout.addLayout(save_layout)
        
        progress_group.setLayout(progress_layout)
        
        # Add retry settings
        retry_layout = QHBoxLayout()
        retry_label = QLabel("Request Retries:")
        self.retry_spin = QSpinBox()
        self.retry_spin.setRange(0, 10)
        self.retry_spin.setValue(3)
        self.retry_spin.setToolTip("Number of times to retry failed requests")
        retry_layout.addWidget(retry_label)
        retry_layout.addWidget(self.retry_spin)
        retry_layout.addStretch(1)
        progress_layout.addLayout(retry_layout)
        
        # Button section
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)
        
        self.send_button = QPushButton("Start Requests")
        self.send_button.setMinimumHeight(36)
        self.send_button.clicked.connect(self.start_requests)
        
        self.stop_button = QPushButton("Stop")
        self.stop_button.setMinimumHeight(36)
        self.stop_button.clicked.connect(self.stop_requests)
        self.stop_button.setEnabled(False)
        self.stop_button.setStyleSheet(f"background-color: {self.COLORS['error']}")
        
        self.clear_button = QPushButton("Clear")
        self.clear_button.setMinimumHeight(36)
        self.clear_button.clicked.connect(self.clear_response)
        self.clear_button.setStyleSheet(f"background-color: {self.COLORS['secondary']}")
        
        button_layout.addWidget(self.send_button)
        button_layout.addWidget(self.stop_button)
        button_layout.addWidget(self.clear_button)
        
        # Response section
        response_label = QLabel("Response:")
        self.response_text = QTextEdit()
        self.response_text.setReadOnly(True)
        
        # Add all layouts to main layout
        main_layout.addLayout(url_layout)
        main_layout.addLayout(ua_layout)
        main_layout.addLayout(custom_ua_layout)
        main_layout.addWidget(config_group)
        main_layout.addWidget(progress_group)
        main_layout.addLayout(button_layout)
        main_layout.addWidget(response_label)
        main_layout.addWidget(self.response_text)
        
        # Set the main layout
        main_widget.setLayout(main_layout)
        self.setCentralWidget(main_widget)
        
        # Connect signals
        self.status_signal.connect(self.update_status)
        self.update_signal.connect(self.update_response)
        self.progress_signal.connect(self.update_progress)
        self.debug_signal.connect(self.send_debug_message)
        
        # Send initial message to debug console
        self.debug_signal.emit("[INFO] Watchdog initialized and ready", "GREEN")
        
        # Setup timer for periodic UI updates
        self.update_timer = QTimer(self)
        # Add refresh_ui method for the timer
        def refresh_ui():
            if self.start_time and not self.stop_requested:
                self.update_stats()
                
                # Update debug console
                if hasattr(self, 'url_input'):
                    elapsed = (datetime.now() - self.start_time).total_seconds()
                    rate = self.request_count / elapsed if elapsed > 0 else 0
                    self.debug_console.update_status(
                        self.url_input.text(),
                        self.request_count,
                        self.success_count,
                        self.fail_count,
                        rate
                    )
                
        self.refresh_ui = refresh_ui
        self.update_timer.timeout.connect(self.refresh_ui)
        self.update_timer.start(500)  # 500ms update interval
        
        # Since we're using CLI debug console, no need for a button
        # But we can add a refresh stats button instead
        refresh_button = QPushButton("Refresh Stats")
        refresh_button.clicked.connect(lambda: self.update_stats(True))
        refresh_button.setStyleSheet(f"background-color: {self.COLORS['dark']}; color: white;")
        button_layout.addWidget(refresh_button)
        
    def on_ua_changed(self, text):
        if text == "Custom":
            self.custom_ua_input.setEnabled(True)
        else:
            self.custom_ua_input.setEnabled(False)
            
    def get_current_user_agent(self):
        current_selection = self.ua_combo.currentText()
        if current_selection == "Custom":
            return self.custom_ua_input.text()
        return self.user_agents[current_selection]
    
    @lru_cache(maxsize=16)
    def get_random_user_agents(self, count):
        """Get a list of random user agents from the available ones"""
        try:
            agents = list(self.user_agents.items())
            # Remove the "Custom" option for random selection
            agents = [a for a in agents if a[0] != "Custom"]
            
            if not agents:
                return []
                
            if count >= len(agents):
                return [agent[1] for agent in agents]  # Return all available agents
            
            selected = random.sample(agents, count)
            return [agent[1] for agent in selected]
        except Exception as e:
            self.update_signal.emit(f"Error selecting user agents: {str(e)}\n")
            # Return a safe default if there's an error
            return ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"]
    def select_save_file(self):
        """Open a file dialog to select a save location"""
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save Results As",
            os.path.join(os.path.expanduser("~"), "request_results.csv"),
            "CSV Files (*.csv);;Text Files (*.txt);;All Files (*)"
        )
        
        if file_path:
            self.save_path = file_path
            self.save_path_label.setText(os.path.basename(file_path))
            return True
        return False
    
    def start_requests(self):
        """Start the request process with asyncio and aiohttp"""
        url = self.url_input.text().strip()
        if not url:
            QMessageBox.warning(self, "Input Error", "Please enter a URL")
            return
            
        if not (url.startswith("http://") or url.startswith("https://")):
            url = "https://" + url
            self.url_input.setText(url)
        
        # Get configuration
        num_threads = min(self.threads_spin.value(), 500)  # Ensure max 500 threads
        num_requests = self.requests_spin.value()
        num_user_agents = self.ua_count_spin.value()
        timeout = self.timeout_spin.value()
        rate_limit = self.rate_limit_spin.value()
        delay = self.delay_spin.value()
        pool_size = self.pool_spin.value()
        http_method = self.method_combo.currentText()
        
        # Check save file
        self.save_results = self.save_checkbox.isChecked()
        if self.save_results and not self.save_path:
            result = self.select_save_file()
            if not result:
                return  # User canceled file selection
        
        # Get user agents
        if self.ua_combo.currentText() == "Custom" and self.custom_ua_input.text():
            user_agents = [self.custom_ua_input.text()]
        else:
            user_agents = self.get_random_user_agents(num_user_agents)
        
        if not user_agents:
            QMessageBox.warning(self, "Input Error", "No valid user agent available")
            return
            
        # Reset counters and UI
        self.request_count = 0
        self.success_count = 0
        self.fail_count = 0
        self.active_threads = 0
        self.stop_requested = False
        self.start_time = datetime.now()
        self.response_times = []
        
        self.response_text.clear()
        self.response_text.setPlainText("Starting requests...\n")
        self.progress_bar.setValue(0)
        self.progress_bar.setMaximum(num_requests)
        
        # Update UI state
        self.send_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_signal.emit("Running requests...", self.COLORS["success"])
        self.debug_signal.emit(f"[START] Beginning {num_requests} requests to {url} using {num_threads} threads", "CYAN")
        self.update_stats()
        
        # Prepare results file if needed
        if self.save_results:
            try:
                with open(self.save_path, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'Request ID', 'URL', 'Method', 'User Agent', 
                        'Status Code', 'Time (s)', 'Success', 'Error'
                    ])
            except Exception as e:
                self.update_signal.emit(f"Error creating results file: {str(e)}\n")
                self.debug_signal.emit(f"[ERROR] Failed to create results file: {str(e)}", "RED")
        
        # Start the async event loop in a separate thread
        self.stop_requested = False
        threading.Thread(
            target=self.run_async_requests,
            args=(url, user_agents, num_requests, num_threads, timeout, 
                  rate_limit, delay, pool_size, http_method),
            daemon=True
        ).start()
    
    def run_async_requests(self, url, user_agents, num_requests, num_threads, 
                          timeout, rate_limit, delay, pool_size, http_method):
        """Run the async event loop in a separate thread"""
        try:
            # Create a new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Run the async request function
            loop.run_until_complete(
                self.process_requests_async(
                    url, user_agents, num_requests, num_threads, 
                    timeout, rate_limit, delay, pool_size, http_method
                )
            )
        except Exception as e:
            self.update_signal.emit(f"Error in async loop: {str(e)}\n")
        finally:
            # Clean up the event loop properly
            try:
                # Cancel all running tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                    
                # Run loop until tasks are canceled
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                    
                # Close the loop
                loop.run_until_complete(loop.shutdown_asyncgens())
                loop.close()
            except Exception as e:
                self.update_signal.emit(f"Error cleaning up loop: {str(e)}\n")
                
            # Signal completion
            self.update_signal.emit("FINISHED")
    
    async def process_requests_async(self, url, user_agents, num_requests, num_threads, 
                                   timeout, rate_limit, delay, pool_size, http_method):
        """Process all requests using httpx and asyncio"""
        # Set up rate limiting
        request_interval = 1.0 / rate_limit if rate_limit > 0 else 0
        
        # Create a semaphore for concurrency control
        semaphore = asyncio.Semaphore(num_threads)
        
        # Create limits for connection pooling
        limits = httpx.Limits(
            max_connections=pool_size,
            max_keepalive_connections=pool_size
        )
        
        # Create the client with proper settings
        async with httpx.AsyncClient(
            timeout=timeout,
            limits=limits,
            follow_redirects=True
        ) as client:
            # Create tasks for all requests
            tasks = []
            for i in range(num_requests):
                if self.stop_requested:
                    break
                
                # Select a random user agent
                user_agent = random.choice(user_agents)
                
                # Create a task for this request
                task = asyncio.create_task(
                    self.make_request_async(
                        i, client, semaphore, url, user_agent, http_method, 
                        delay, request_interval, self.retry_spin.value()
                    )
                )
                tasks.append(task)
            
            # Wait for all tasks to complete
            if tasks:
                await asyncio.gather(*tasks)
    
    async def make_request_async(self, task_id, client, semaphore, url, 
                               user_agent, http_method, delay, request_interval, retries=3):
        """Make a single async request with rate limiting and retries using httpx"""
        if self.stop_requested:
            return
            
        # Apply rate limiting
        if request_interval > 0:
            await asyncio.sleep(request_interval)
            
        # Apply additional delay if configured
        if delay > 0:
            await asyncio.sleep(delay)
        
        # Generate a cache key for similar requests
        cache_key = f"{http_method}:{url}:{user_agent[:20]}"
            
        # Use the semaphore for concurrency control
        async with semaphore:
            headers = {"User-Agent": user_agent}
            start_time = time.time()
            status_code = None
            error_msg = None
            attempt = 0
            
            # Try the request with retries
            while attempt <= retries:
                if self.stop_requested:
                    return
                    
                if attempt > 0:
                    # Add a small delay between retries (exponential backoff)
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                    
                try:
                    # Check if we have a cached response pattern
                    if cache_key in self.response_cache and random.random() < 0.2:  # 20% chance to use cache
                        # Use cached result for similar requests to minimize server load
                        cached = self.response_cache[cache_key]
                        await asyncio.sleep(cached.get("time", 0.1))  # Simulate response time
                        status_code = cached.get("status", 200)
                        headers_result = cached.get("headers", "")
                        content_preview = cached.get("content", "")
                        is_cached = True
                    else:
                        # Make the actual request
                        is_cached = False
                
                        # Make actual request
                        response = await client.request(
                            method=http_method,
                            url=url,
                            headers=headers
                        )
                        
                        status_code = response.status_code
                        headers_to_show = ['content-type', 'server', 'date']
                        headers_str = ", ".join(
                            f"{k}: {v}" for k, v in response.headers.items() 
                            if k.lower() in headers_to_show
                        )
                        
                        # For HEAD requests, don't try to read content
                        if http_method != "HEAD":
                            # Limit content to prevent UI freeze
                            content = response.text
                            content_preview = content[:200] + "...(content truncated)..." if len(content) > 200 else content
                        else:
                            content_preview = "(HEAD request - no content)"
                            
                        # Cache the response pattern for similar requests
                        if 200 <= status_code < 300:  # Only cache successful responses
                            self.response_cache[cache_key] = {
                                "status": status_code,
                                "headers": headers_str,
                                "content": content_preview,
                                "time": response.elapsed.total_seconds()
                            }
                    
                    # Record success
                    self.success_count += 1
                    elapsed = time.time() - start_time
                    self.response_times.append(elapsed)
                    
                    # Format response info
                    result = f"\n--- Request {task_id + 1} ---\n"
                    if is_cached:
                        result += "(CACHED RESPONSE)\n"
                    result += f"Method: {http_method}\n"
                    result += f"User-Agent: {user_agent}\n"
                    result += f"Status Code: {status_code}\n"
                    result += f"Time: {elapsed:.2f} seconds\n"
                    result += f"Headers: {headers_str}\n"
                    
                    if http_method != "HEAD":
                        result += f"Content Preview: {content_preview}\n"
                    
                    # Save result if needed
                    if self.save_results:
                        self.save_result(
                            task_id, url, http_method, user_agent, 
                            status_code, elapsed, True, ""
                        )
                    
                    # Update UI with result
                    self.update_signal.emit(result)
                    
                    # We succeeded, so break the retry loop
                    break
                    
                except httpx.RequestError as e:
                    error_msg = f"Request error: {str(e)}"
                    # Only increment fail count on the last attempt
                    if attempt == retries:
                        self.fail_count += 1
                except Exception as e:
                    error_msg = f"Error: {str(e)}"
                    # Only increment fail count on the last attempt
                    if attempt == retries:
                        self.fail_count += 1
                
                # Move to next retry attempt
                attempt += 1
                
                # If this was the last attempt and we still have an error
                if attempt > retries and error_msg:
                    elapsed = time.time() - start_time
                    result = f"\n--- Request {task_id + 1} ---\n"
                    result += f"FAILED after {retries+1} attempts\n"
                    result += f"Method: {http_method}\n"
                    result += f"User-Agent: {user_agent}\n"
                    result += f"Error: {error_msg}\n"
                    result += f"Time: {elapsed:.2f} seconds\n"
                    
                    # Save error result if needed
                    if self.save_results:
                        self.save_result(
                            task_id, url, http_method, user_agent, 
                            0, elapsed, False, error_msg
                        )
                    
                    # Update UI with error
                    self.update_signal.emit(result)
            
            # Update progress
            self.request_count += 1
            self.progress_signal.emit(self.request_count)
    
    def save_result(self, task_id, url, http_method, user_agent, status_code, elapsed, success, error):
        """Save a result to the CSV file"""
        try:
            with open(self.save_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    task_id + 1, url, http_method, user_agent, 
                    status_code, f"{elapsed:.2f}", success, error
                ])
        except Exception as e:
            self.update_signal.emit(f"Error saving to file: {str(e)}\n")
    
    def update_response(self, text):
        """Update the response text area - called from the signal"""
        if text == "FINISHED":
            # Special signal to indicate all threads are done
            self.send_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.status_signal.emit("Completed", self.COLORS["success"])
            self.update_stats(final=True)
            
            # Show notification when finished
            elapsed = 0
            if self.start_time:
                elapsed = (datetime.now() - self.start_time).total_seconds()
            self.show_notification(
                "Watchdog Requests Completed", 
                f"Completed {self.request_count} requests in {elapsed:.2f}s\nSuccess: {self.success_count}, Failed: {self.fail_count}"
            )
            
            # Send completion message to debug console
            self.debug_signal.emit(f"[COMPLETE] Finished all requests: {self.success_count} successful, {self.fail_count} failed", "GREEN")
            return
            
        # Append text to the response area
        cursor = self.response_text.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(text)
        self.response_text.setTextCursor(cursor)
        
        # Update statistics
        self.update_stats()
    
    def update_progress(self, value):
        """Update the progress bar - called from the signal"""
        self.progress_bar.setValue(value)
        self.update_stats()
    
    def update_stats(self, final=False):
        """Update the statistics label"""
        elapsed = 0
        if self.start_time:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            
        stats = f"Requests: {self.request_count}/{self.progress_bar.maximum()} | "
        stats += f"Success: {self.success_count} | "
        stats += f"Failed: {self.fail_count} | "
        stats += f"Time: {elapsed:.2f}s"
        
        if final and self.request_count > 0:
            stats += f" | Avg: {elapsed/self.request_count:.2f}s per request"
            if self.response_times:
                avg_time = sum(self.response_times) / len(self.response_times)
                min_time = min(self.response_times) if self.response_times else 0
                max_time = max(self.response_times) if self.response_times else 0
                stats += f" | Response time: min={min_time:.2f}s avg={avg_time:.2f}s max={max_time:.2f}s"
            if self.success_count > 0:
                success_rate = (self.success_count / self.request_count) * 100
                stats += f" | Success rate: {success_rate:.1f}%"
        
        self.stats_label.setText(stats)
    
    def update_status(self, message, color):
        """Update the status label with message and color"""
        self.status_label.setText(message)
        self.status_label.setStyleSheet(f"color: {color};")
    
    def stop_requests(self):
        """Stop all ongoing requests"""
        self.stop_requested = True
        self.update_signal.emit("\n--- Stopping requests... ---\n")
        self.status_signal.emit("Stopping requests...", self.COLORS["warning"])
        self.stop_button.setEnabled(False)
        
        # If all threads are already done, reset the UI immediately
        if self.active_threads == 0:
            self.send_button.setEnabled(True)
    
    def clear_response(self):
        self.response_text.clear()

def get_application_stylesheet(colors):
    """Return the application stylesheet"""
    return f"""
        QMainWindow {{
            background-color: {colors["background"]};
        }}
        QWidget {{
            font-family: 'Segoe UI', Arial, sans-serif;
        }}
        QGroupBox {{
            border: 1px solid #BDBDBD;
            border-radius: 5px;
            margin-top: 10px;
            font-weight: bold;
            padding: 10px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            subcontrol-position: top left;
            left: 10px;
            padding: 0 5px;
            color: {colors["primary"]};
        }}
        QPushButton {{
            background-color: {colors["primary"]};
            color: white;
            border: none;
            border-radius: 4px;
            padding: 6px 12px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: #1F65D6;
        }}
        QPushButton:pressed {{
            background-color: #0D47A1;
        }}
        QPushButton:disabled {{
            background-color: #BDBDBD;
        }}
        QProgressBar {{
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            text-align: center;
            height: 20px;
        }}
        QProgressBar::chunk {{
            background-color: {colors["primary"]};
            width: 10px;
            margin: 0.5px;
        }}
        QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            padding: 4px 8px;
            background: white;
            min-height: 25px;
        }}
        QTextEdit {{
            border: 1px solid #BDBDBD;
            border-radius: 4px;
            padding: 4px;
            background: white;
        }}
        QLabel {{
            padding: 2px;
        }}
        QCheckBox {{
            spacing: 5px;
        }}
    """

def main():
    # Set correct event loop policy for Windows
    if platform.system() == 'Windows':
        # Use selector event loop policy on Windows to avoid issues with ProactorEventLoop
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    app = QApplication(sys.argv)
    
    # Apply stylesheet to application instance
    app.setStyleSheet(get_application_stylesheet(WatchdogTool.COLORS))
    
    window = WatchdogTool()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()


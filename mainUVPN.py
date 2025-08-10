from PyQt5.QtWidgets import QMainWindow, QApplication, QWidget, QPushButton
from PyQt5.QtWidgets import QComboBox, QGroupBox, QMenu, QGraphicsDropShadowEffect
from PyQt5.QtWidgets import QGridLayout, QScrollArea, QLabel, QToolButton
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QMessageBox, QStyle, QAction
from PyQt5.QtWidgets import QSystemTrayIcon, QTextEdit, QDialog, QSpinBox, QLineEdit
from PyQt5.QtWidgets import QFormLayout, QDialogButtonBox
from PyQt5 import QtCore
from PyQt5.QtCore import QPoint, QSize, QSettings, pyqtSignal
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPalette, QColor, QFont
import constants as cnts
import threading
from typing import Iterable
import sys, os
import time
import atexit
from lib.tools import pinger, handle_ping, resource_path, find_servers, get_best_connection, download_connection, find_existing_openvpn
from lib.openvpnclient import OpenVPNClient, VPNStatus
# from lib.servers import SERVERS
from version_handler import __version__
import webbrowser
from loguru import logger
log = logger.bind(name="UMVPN-logger")

class GUI(QWidget):
    # Signal for thread-safe output updates
    output_signal = pyqtSignal(str)
    
    def __init__(self, parent) -> None:
        super().__init__(parent)
        self.output_signal.connect(self.append_output)
        self.load_settings()
        self.settings_window = None
        self.colors = ["green", "orange", "red", "grey"]
        #Initialize layouts
        self.layout = QVBoxLayout(self)
        layout = QVBoxLayout()
        gridLayout = QGridLayout()
        #Initialize widgets
        self.ping_text = "Waiting..."
        logolayout = self.load_title()
        combolayout = self.load_actions()
        self.servergroup, self.serverlayout = self.load_current_server()
        outputlayout = self.load_output()
        gridLayout.addWidget(logolayout, 0,0,1,1)
        gridLayout.addWidget(combolayout, 1,0,1,1)
        gridLayout.addWidget(self.servergroup, 2,0,1,1)
        gridLayout.addWidget(outputlayout, 3,0,1,1)
        #
        gridLayout.setRowStretch(3, 1)  # Give output section most space
        layout.addLayout(gridLayout)
        self.layout.addLayout(layout)
        self.setLayout(self.layout)
        
        # Load saved mode selection
        self.load_saved_mode()
    
    def __threaded_option(self,func: object = None,args: Iterable = ()):
        thread = threading.Thread(target=func,args=args)
        thread.daemon = True
        thread.start()
    
    def _set_icon(self, object, path):
        object.setIcon(QIcon(path))
    
    def _check_updates(self):
        webbrowser.open(cnts.UPDATE_ENDPOINT, new=2)
    
    def load_title(self):
        group = QWidget()
        layout = QHBoxLayout()
        #
        ellipsis = QToolButton(self)
        ellipsis.setPopupMode(QToolButton.InstantPopup)
        ellipsis.setText("...")
        #
        menu = QMenu(self)
        action_update = QAction("Check for updates",self)
        action_update.triggered.connect(lambda: self.__threaded_option(func=self._check_updates))
        action_options = QAction("Options",self)
        action_options.triggered.connect(self._show_options)
        menu.addAction(action_update)
        menu.addSeparator()
        menu.addAction(action_options)
        ellipsis.setMenu(menu)
        ellipsis.setStyleSheet("QToolButton::menu-indicator { image: none; }")
        #
        github_button = QPushButton()
        github_button.setStyleSheet("QPushButton:hover { background-color:none; }")
        github_button.setIcon(QIcon(resource_path(os.path.join('res','github-mark-white.png'))))
        github_button.setIconSize(QtCore.QSize(16,16))
        github_button.setMaximumWidth(16)
        github_button.enterEvent = (lambda event: self._set_icon(github_button,resource_path(os.path.join('res','github-mark.png'))))
        github_button.leaveEvent = (lambda event: self._set_icon(github_button,resource_path(os.path.join('res','github-mark-white.png'))))
        github_button.setToolTip('GitHub')
        github_button.setFlat(True)
        github_button.clicked.connect(lambda: webbrowser.open(cnts.GITHUB_ENDPOINT, new=2))
        #
        label = QLabel()
        label.setText(f'<font size="7"><b>Uma Musume VPN</b></font> &nbsp;&nbsp;<font size="6" color="#2E313F">V{__version__}</font>')
        layout.addWidget(label)
        layout.addWidget(github_button)
        layout.addWidget(ellipsis)
        #
        group.setLayout(layout)
        return group

    def load_actions(self):
        group = QGroupBox("Select Mode:")
        layout = QGridLayout()
        self.regionComboBox = QComboBox(self)
        self.regionComboBox.addItems(["JP", "JP+DMM", "Global"])
        self.regionComboBox.currentTextChanged.connect(self.save_selected_mode)
        self.connectButton = QPushButton("Connect")
        self.disconnectButton = QPushButton("Disconnect")
        self.disconnectButton.setEnabled(False)
        self.connectButton.clicked.connect(self.toggle_connection)
        self.disconnectButton.clicked.connect(self.toggle_connection)
        self.is_connected = False
        self.vpn_client = None
        
        layout.addWidget(self.regionComboBox, 0, 0, 1, 2)
        layout.addWidget(self.connectButton, 1, 0)
        layout.addWidget(self.disconnectButton, 1, 1)
        
        group.setLayout(layout)
        return group
    
    def load_output(self):
        group = QGroupBox("Output:")
        layout = QVBoxLayout()
        self.output_text = QTextEdit()
        self.output_text.setReadOnly(True)
        self.output_text.setStyleSheet("""
            QTextEdit {
                background-color: black; 
                color: white; 
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 10pt;
                padding: 5px;
            }
        """)        
        layout.addWidget(self.output_text)
        group.setLayout(layout)
        return group
    
    def append_output(self, text):
        """Thread-safe method to append text to output."""
        self.output_text.append(text)
        self.output_text.ensureCursorVisible()
    
    def log_output(self, text):
        """Thread-safe method to log output from any thread."""
        self.output_signal.emit(text)

    def load_current_server(self):
        group = QGroupBox()
        layout = QGridLayout()
        self.qlinear = QLabel()
        self.plinear = QLabel()
        self.update_current_server()
        layout.addWidget(self.qlinear, 0, 0)
        layout.addWidget(self.plinear, 0, 1, alignment=Qt.AlignRight)
        group.setLayout(layout)
        return group, layout
        
    def update_current_server(self):
        if self.is_connected:
            region = self.regionComboBox.currentText()
            self.qlinear.setText(f"Connected to: {region}")
            self.plinear.setText(f'Status: <font color="green">Connected</font>')
            # Update tray status
            if hasattr(self.parent(), 'status_action'):
                self.parent().status_action.setText(f"Connected to: {region}")
        else:
            self.qlinear.setText("Status: Disconnected")
            self.plinear.setText(f'Status: <font color="red">Disconnected</font>')
            # Update tray status
            if hasattr(self.parent(), 'status_action'):
                self.parent().status_action.setText("Disconnected")

    def toggle_connection(self):
        if self.is_connected:
            self.log_output("Disconnecting VPN...")
            self.__threaded_option(func=self._disconnect_vpn)
        else:
            region = self.regionComboBox.currentText()
            
            # Check for existing OpenVPN processes before connecting
            existing_processes = find_existing_openvpn()
            if existing_processes:
                # Ask user for confirmation to terminate existing processes
                if not self._confirm_process_termination(len(existing_processes)):
                    self.log_output("Connection cancelled - existing VPN processes not terminated")
                    return
            
            self.log_output(f"Connecting to {region}...")
            # Update UI immediately to show connecting state
            self.connectButton.setEnabled(False)
            self.qlinear.setText("Status: Connecting...")
            self.plinear.setText(f'Status: <font color="orange">Connecting</font>')
            # Run connection in background thread
            self.__threaded_option(func=self._connect_vpn, args=(region,))
    
    def _connect_vpn(self, region):
        """Background thread method for VPN connection."""
        try:
            # Clean up any existing OpenVPN processes (user already confirmed)
            existing_processes = find_existing_openvpn()
            if existing_processes:
                self.log_output("Cleaning up existing VPN connections...")
                self._terminate_openvpn_processes(existing_processes)
            
            types = {
                "JP": {"sites": "uma"},
                "JP+DMM": {"sites": "uma", "sites": "dmm"},
                "Global": {"sites": "umag"}
            }
            sel = types[region]
            self.log_output("Finding servers...")
            status, response = find_servers(sel)
            
            if not status:
                self.log_output("ERROR: Failed to find servers")
                self._reset_connect_state()
                return
                
            config_path = resource_path(f"_vcache.ovpn")
            best_connection = get_best_connection(response["data"])
            download_connection(best_connection[0]["ip"], config_path)
            self.vpn_client = OpenVPNClient(
                config_path=config_path, 
                on_status_change=self.on_vpn_status_change,
                management_host=self.vpn_management_host,
                management_port=self.vpn_management_port
            )
            self.vpn_client.start()
            
        except FileNotFoundError as e:
            self.log_output(f"ERROR: Config not found for {region}")
            log.exception(f"Config file not found for region {region}")
            self._reset_connect_state()
            self._call_error_window("Config not found!", f"The VPN configuration for {region} was not found.")
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error ({type(e).__name__})"
            self.log_output(f"ERROR: {error_msg}")
            log.exception("VPN connection error")
            self._reset_connect_state()
            self._call_error_window("Connection Error", error_msg)
    
    def _disconnect_vpn(self):
        """Background thread method for VPN disconnection."""
        try:
            # self.stop_ping()
            if self.vpn_client:
                self.vpn_client.stop()
            self.connectButton.setEnabled(True)
            self.disconnectButton.setEnabled(False)
            self.is_connected = False
            self.update_current_server()
        except Exception as e:
            error_msg = str(e) if str(e) else f"Unknown error ({type(e).__name__})"
            self.log_output(f"ERROR during disconnect: {error_msg}")
            log.exception("VPN disconnect error")
    
    def _reset_connect_state(self):
        """Reset UI to disconnected state on connection failure."""
        self.connectButton.setEnabled(True)
        self.qlinear.setText("Status: Disconnected")
        self.plinear.setText(f'Status: <font color="red">Disconnected</font>')
    
    def on_vpn_status_change(self, status: VPNStatus, message: str):
        if status == VPNStatus.CONNECTED:
            self.log_output("VPN Connected successfully!")
            self.connectButton.setEnabled(False)
            self.disconnectButton.setEnabled(True)
            self.is_connected = True
            self.update_current_server()
            self.__threaded_option(func=self.ping_event_loop)
        elif status in (VPNStatus.DISCONNECTED, VPNStatus.ERROR):
            if status == VPNStatus.DISCONNECTED:
                self.log_output("VPN Disconnected")
            else:
                self.log_output(f"VPN ERROR: {message}")
                log.exception(f"VPN status error: {message}")
            
            # Always reset to disconnected state on any non-connected status
            self._force_disconnect_state()
            
            if status == VPNStatus.ERROR:
                self._call_error_window("VPN Error", message)
    
    def _force_disconnect_state(self):
        """Force UI and state to disconnected, regardless of current state."""
        try:
            # self.stop_ping()  # Already commented out per user's edit
            self.connectButton.setEnabled(True)
            self.disconnectButton.setEnabled(False)
            self.is_connected = False
            self.update_current_server()
        except Exception as e:
            log.exception("Error forcing disconnect state")
    
    
    
    def _confirm_process_termination(self, process_count):
        """Ask user for confirmation before terminating existing VPN processes."""
        msg = QMessageBox(self.parent())
        msg.setIcon(QMessageBox.Question)
        msg.setWindowTitle("Existing VPN Connection")
        
        if process_count == 1:
            msg.setText("<b>Existing VPN Process Detected</b>")
            msg.setInformativeText(
                "An OpenVPN process is already running. "
                "This may interfere with the new connection.\n\n"
                "Do you want to terminate it and proceed?"
            )
        else:
            msg.setText("<b>Multiple VPN Processes Detected</b>")
            msg.setInformativeText(
                f"{process_count} OpenVPN processes are already running. "
                "These may interfere with the new connection.\n\n"
                "Do you want to terminate them and proceed?"
            )
        
        msg.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg.setDefaultButton(QMessageBox.Yes)
        
        # Set always-on-top in dev mode
        if self.parent().dev_mode:
            msg.setWindowFlags(msg.windowFlags() | Qt.WindowStaysOnTopHint)
        
        result = msg.exec_()
        return result == QMessageBox.Yes
    
    def _terminate_openvpn_processes(self, processes):
        """Terminate the specified OpenVPN processes."""
        try:
            killed_count = 0
            for proc in processes:
                try:
                    log.info(f"Terminating existing OpenVPN process (PID: {proc.pid})")
                    proc.terminate()
                    killed_count += 1
                    # Wait briefly for graceful termination
                    try:
                        proc.wait(timeout=3)
                    except psutil.TimeoutExpired:
                        # Force kill if it doesn't terminate gracefully
                        proc.kill()
                        log.warning(f"Force killed OpenVPN process (PID: {proc.pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    # Process already gone or no access
                    continue
            
            if killed_count > 0:
                self.log_output(f"Terminated {killed_count} existing OpenVPN process(es)")
                log.info(f"Terminated {killed_count} existing OpenVPN processes")
                # Brief pause to ensure processes are fully terminated
                time.sleep(1)
                
        except Exception as e:
            log.exception("Error during OpenVPN process termination")
            self.log_output("Warning: Could not complete OpenVPN cleanup")

    # def ping_event_loop(self):
    #     region = self.regionComboBox.currentText()
    #     server = SERVERS.get(region)
    #     if not server:
    #         self._set_text(f"No server found for {region}", color="red")
    #         return

    #     colors = ["green", "orange", "red", "grey"] # Grey is for error checking
    #     def color_coding(ping):
    #         try:
    #             ping = int(ping)
    #         except (TypeError, ValueError):
    #             ping = -1 #indicates error
    #         if ping <= 100 and ping != -1:
    #             return 0
    #         elif ping > 100 and ping <= 200:
    #             return 1
    #         elif ping > 200:
    #             return 2
    #         else:
    #             return 3

    #     self.pinging = True
    #     while self.pinging:
    #         ping_response = pinger(server)
    #         if ping_response:
    #             ping = ping_response.rtt_avg_ms
    #             loss = ping_response.packet_loss
    #             color = colors[color_coding(ping)]
    #             self._reset_text()
    #             self._set_text(f"{region} ({server}) -- ping: {ping}ms -- loss {loss*100}%", color=color)
    #             self._update_text()
    #         else:
    #             self._reset_text()
    #             self._set_text(f"Pinging {region} ({server}) failed.", color="red")
    #             self._update_text()
    #             break 
    #         time.sleep(1)

    # def stop_ping(self):
    #     self.pinging = False
    def load_ping(self):
        ...
    # def load_ping(self):
    #     group = QGroupBox("Ping:")
    #     layout = QGridLayout()
    #     self.qline = QLabel()
    #     self.qline.setStyleSheet("background-color: black;")
    #     self.qline.setAlignment(QtCore.Qt.AlignTop)
    #     self.qline.setAutoFillBackground(True)
    #     layout.addWidget(self.qline,2,0,1,3)
    #     group.setLayout(layout)
    #     return group

    def _reset_text(self):
        self.ping_text = ""

    def _set_text(self, text, color= "#000000", last=False):
        oldText = self.ping_text
        if last:
            newText = f'<font color="{color}">{text}</font>'
        else:
            newText = f'<font color="{color}">{text}</font><br>'
        self.ping_text = oldText + newText
    
    def _update_text(self):
        self.qline.setText(self.ping_text)
    
    def load_settings(self):
        """Load VPN settings from storage."""
        settings = QSettings("UMVPN", "Settings")
        self.vpn_management_port = settings.value("vpn_management_port", 25340, type=int)
        self.vpn_management_host = settings.value("vpn_management_host", "127.0.0.1", type=str)
        
    def save_settings(self):
        """Save VPN settings to storage."""
        settings = QSettings("UMVPN", "Settings")
        settings.setValue("vpn_management_port", self.vpn_management_port)
        settings.setValue("vpn_management_host", self.vpn_management_host)
        
    def save_selected_mode(self, mode):
        """Save the currently selected mode."""
        settings = QSettings("UMVPN", "Settings")
        settings.setValue("last_selected_mode", mode)
        
    def load_saved_mode(self):
        """Load and set the last selected mode."""
        settings = QSettings("UMVPN", "Settings")
        last_mode = settings.value("last_selected_mode", "JP", type=str)
        index = self.regionComboBox.findText(last_mode)
        if index >= 0:
            self.regionComboBox.setCurrentIndex(index)
    
    def _show_options(self):
        """Show the options dialog."""
        if self.settings_window is None:
            self.settings_window = OptionsDialog(self.parent(), self)
        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _call_error_window(self, title, message):
        msg = QMessageBox(self.parent())
        msg.setIcon(QMessageBox.Critical)
        msg.setText(f'<b>{title}</b>')
        msg.setInformativeText(message)
        msg.setWindowTitle("Error")
        if self.parent().dev_mode:
            msg.setWindowFlags(msg.windowFlags() | Qt.WindowStaysOnTopHint)
        msg.exec_()

class OptionsDialog(QDialog):
    """Options dialog for VPN settings configuration."""
    
    def __init__(self, parent, gui_widget):
        super().__init__(parent)
        self.gui_widget = gui_widget
        self.setWindowTitle("Options")
        self.setModal(True)
        self.setFixedSize(300, 150)
        
        # Create layout
        layout = QFormLayout()
        
        # VPN Management Host
        self.host_input = QLineEdit()
        self.host_input.setText(self.gui_widget.vpn_management_host)
        layout.addRow("Management Host:", self.host_input)
        
        # VPN Management Port
        self.port_input = QSpinBox()
        self.port_input.setRange(1024, 65535)
        self.port_input.setValue(self.gui_widget.vpn_management_port)
        layout.addRow("Management Port:", self.port_input)
        
        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept_settings)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)
        
        self.setLayout(layout)
        
    def accept_settings(self):
        """Apply and save the settings."""
        # Update GUI widget settings
        self.gui_widget.vpn_management_host = self.host_input.text()
        self.gui_widget.vpn_management_port = self.port_input.value()
        
        # Save to persistent storage
        self.gui_widget.save_settings()
        
        # Log the changes
        log.info(f"VPN settings updated - Host: {self.gui_widget.vpn_management_host}, Port: {self.gui_widget.vpn_management_port}")
        self.gui_widget.log_output(f"Settings updated - Host: {self.gui_widget.vpn_management_host}, Port: {self.gui_widget.vpn_management_port}")
        
        self.accept()

class Window(QMainWindow):
    def __init__(self, dev_mode=False):
        super(Window, self).__init__()
        self.dev_mode = dev_mode
        self.width_usr = 640
        self.height_usr = 470
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.FramelessWindowHint)
        self.setMaximumSize(self.width_usr,self.height_usr)
        self.setWindowTitle("UMVPN")
        self.setWindowIcon(QIcon(resource_path(os.path.join("res", "umvpn_icon.png"))))
        self.table_widget = GUI(self)
        #
        self.titleBar = MyBar(self)
        self.setContentsMargins(0, self.titleBar.height(), 0, 0)
        self.resize(self.width_usr, self.titleBar.height() + self.height_usr)
        self.setCentralWidget(self.table_widget)
        
        # Register cleanup for unexpected termination
        atexit.register(self.cleanup_vpn)
        
        # Set up system tray
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(QIcon(resource_path(os.path.join("res", "umvpn_icon.png"))))
        self.tray_icon.activated.connect(self.tray_icon_activated)
        
        # Create tray menu
        self.tray_menu = QMenu()
        self.status_action = QAction("Disconnected", self)
        self.status_action.setEnabled(False)
        self.exit_action = QAction("Exit", self)
        self.exit_action.triggered.connect(self.close)
        
        self.tray_menu.addAction(self.status_action)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction(self.exit_action)
        self.tray_icon.setContextMenu(self.tray_menu)
        
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon.show()
        
        # Set initial position and restore if needed
        if self.dev_mode:
            self.setWindowFlags(self.windowFlags() | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
            self.restorePosition()
        self.show()
    
    def changeEvent(self, event):
        if event.type() == event.WindowStateChange:
            self.titleBar.windowStateChanged(self.windowState())

    def resizeEvent(self, event):
        self.titleBar.resize(self.width(), self.titleBar.height())
    
    def tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show()
                self.raise_()
                self.activateWindow()
        
    def moveEvent(self, event):
        # Save position on move in dev mode
        if self.dev_mode:
            try:
                with open('.dev_window_pos', 'w') as f:
                    f.write(f"{self.x()},{self.y()}")
            except Exception as e:
                log.exception("Error saving window position to file")

    def closeEvent(self, event):
        close = QMessageBox()
        close.setWindowTitle("Close")
        close.setText("You sure?")
        close.setStandardButtons(QMessageBox.Yes | QMessageBox.Cancel)
        if self.dev_mode:
            close.setWindowFlags(close.windowFlags() | Qt.WindowStaysOnTopHint)
        close = close.exec()
        if close == QMessageBox.Yes:
            # Cleanup VPN before closing
            self.cleanup_vpn()
            # Save window position in dev mode
            if self.dev_mode:
                self.savePosition()
            self.table_widget.close()
            event.accept()
        else:
            event.ignore()
    
    def cleanup_vpn(self):
        """Cleanup VPN connection on app termination."""
        try:
            if hasattr(self, 'table_widget') and hasattr(self.table_widget, 'vpn_client'):
                if self.table_widget.vpn_client and self.table_widget.is_connected:
                    log.info("Cleaning up VPN connection on app exit")
                    self.table_widget.vpn_client.stop()
        except Exception as e:
            log.exception("Error during VPN cleanup")
    
    def savePosition(self):
        settings = QSettings("UMVPN", "WindowPosition")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("pos", self.pos())
        
        # Also save to file for dev-tools
        if self.dev_mode:
            try:
                with open('.dev_window_pos', 'w') as f:
                    f.write(f"{self.x()},{self.y()}")
            except Exception as e:
                log.exception("Error saving window position to file")
    
    def restorePosition(self):
        # Check for position from dev-tools first
        dev_pos = os.environ.get('UMVPN_DEV_POS')
        print(f"Dev pos: {dev_pos}")
        if dev_pos:
            log.info(f"Restoring position from dev-tools: {dev_pos}")
            try:
                x, y = map(int, dev_pos.split(','))
                self.move(x, y)
                return
            except ValueError as e:
                log.exception("Error parsing dev position")
        
        # Fallback to QSettings
        settings = QSettings("UMVPN", "WindowPosition")
        geometry = settings.value("geometry")
        pos = settings.value("pos")
        if geometry:
            self.restoreGeometry(geometry)
        elif pos:
            self.move(pos)


class MyBar(QWidget):
    clickPos = None
    #https://stackoverflow.com/questions/44241612/custom-titlebar-with-frame-in-pyqt5
    def __init__(self, parent):
        super(MyBar, self).__init__(parent)
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.Shadow)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.addStretch()
        background = QWidget(self)
        background.setLayout(layout)
        background.setFixedWidth(parent.width())
        background.setStyleSheet("background-color: #080808; border-radius: 0;")
        self.title = QLabel(self, alignment=Qt.AlignCenter)
        self.title.setText(f'<font color="white">{parent.windowTitle()}</font>')

        style = self.style()
        ref_size = self.fontMetrics().height()
        ref_size += style.pixelMetric(style.PM_ButtonMargin) * 2
        self.setMaximumHeight(ref_size + 2)

        btn_size = QSize(ref_size, ref_size)
        # for target in ('min', 'normal', 'max', 'close'):
        for target in ('min', 'close'):
            btn = QToolButton(self, focusPolicy=Qt.NoFocus)
            layout.addWidget(btn)
            btn.setFixedSize(btn_size)

            iconType = getattr(style, 
                'SP_TitleBar{}Button'.format(target.capitalize()))
            btn.setIcon(style.standardIcon(iconType))

            if target == 'close':
                colorNormal = 'red'
                colorHover = 'orangered'
            else:
                colorNormal = 'palette(mid)'
                colorHover = 'palette(light)'
            btn.setStyleSheet('''
                QToolButton {{
                    background-color: {};
                }}
                QToolButton:hover {{
                    background-color: {}
                }}
            '''.format(colorNormal, colorHover))

            signal = getattr(self, target + 'Clicked')
            btn.clicked.connect(signal)

            setattr(self, target + 'Button', btn)

        # self.normalButton.hide()

        self.updateTitle(parent.windowTitle())
        parent.windowTitleChanged.connect(self.updateTitle)

    def updateTitle(self, title=None):
        if title is None:
            title = self.window().windowTitle()
        width = self.title.width()
        width -= self.style().pixelMetric(QStyle.PM_LayoutHorizontalSpacing) * 2
        self.title.setText(self.fontMetrics().elidedText(
            title, Qt.ElideRight, width))

    def windowStateChanged(self, state):
        print("WindowStateChanged ", state)
    #     self.normalButton.setVisible(state == Qt.WindowMaximized)
    #     self.maxButton.setVisible(state != Qt.WindowMaximized)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clickPos = event.windowPos().toPoint()

    def mouseMoveEvent(self, event):
        if self.clickPos is not None:
            self.window().move(event.globalPos() - self.clickPos)

    def mouseReleaseEvent(self, QMouseEvent):
        self.clickPos = None

    def closeClicked(self):
        self.window().close()

    def maxClicked(self):
        self.window().showMaximized()

    def normalClicked(self):
        self.window().showNormal()

    def minClicked(self):
        self.window().hide()

    def resizeEvent(self, event):
        self.title.resize(self.minButton.x(), self.height())
        self.updateTitle()

def create_app():
    """Create and configure the QApplication."""
    import qdarktheme
    qdarktheme.enable_hi_dpi()
    app = QApplication(sys.argv)
    app.setStyleSheet('QMainWindow')
    qdarktheme.setup_theme(
        theme="auto",
        custom_colors={
            "[dark]": {
                "primary": "df80ff"
            }
        }
        )
    return app

def main():
    """Main application entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="UMVPN Client")
    parser.add_argument("--dev", action="store_true", 
                       help="Run in development mode with auto-reload")
    parser.add_argument("--no-reload", action="store_true",
                       help="Disable auto-reload in development mode")
    parser.add_argument("--pos", help="Window position as 'x,y'")
    
    args = parser.parse_args()
    
    # Set position globally for window creation
    if args.pos and args.dev:
        try:
            x, y = map(int, args.pos.split(','))
            os.environ['UMVPN_DEV_POS'] = f"{x},{y}"
        except ValueError:
            pass
    
    if args.dev:
        # Run in development mode
        log.info("Starting in development mode...")
        if args.no_reload:
            # Development mode without auto-reload
            log.info("Auto-reload disabled")
            app = create_app()
            window = Window(dev_mode=True)

            sys.exit(app.exec_())
        else:
            # Use the development tools for auto-reload
            try:
                from dev_tools import DevModeRunner
                log.info("Auto-reload enabled. The application will restart when you save Python files.")
                runner = DevModeRunner(__file__)
                runner.run()
            except ImportError:
                log.warning("Development tools not available. Install 'watchdog' package.")
                log.info("Running in normal mode...")
                app = create_app()
                window = Window(dev_mode=True)
    
                sys.exit(app.exec_())
    else:
        # Normal production mode
        app = create_app()
        window = Window(dev_mode=False)
        sys.exit(app.exec_())

if __name__ == "__main__":
    main()